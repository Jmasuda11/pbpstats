"""Versioned rules for NBA team technicals and excess timeouts recorded with neither a team
nor a person."""

import hashlib
import json

import pytest

from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3Context,
    V3DecodeError,
    web,
)
from pbpstats.data_loader.stats_nba_v3.decoder import (
    TEAMLESS_EXCESS_TIMEOUT_VERSION,
    TEAMLESS_TECHNICAL_VERSION,
)
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, e, encode_v3, wrap

DATA = ROOT / "tests/parity/data/recorded_evidence"
UTA, TOR, OKC, POR, PHI, CHI, CLE = (
    1610612762, 1610612761, 1610612760, 1610612757, 1610612755, 1610612741, 1610612739,
)


def load(rows, game="0022500001"):
    source = json.dumps({"game": {"gameId": game, "actions": rows}}).encode()
    roster = {
        p: {"team_id": team, "names": [f"Player{p}"]}
        for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for p in players
    }
    context = V3Context(
        game, (HOME, AWAY), roster,
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Controlled team-technical context", hashlib.sha256(source).hexdigest(),
    )
    return StatsNbaV3PossessionLoader.from_context(source, context)


def delay_technical(violation=None, shooters=(AWAY,), subtype="Delay Technical"):
    """HOME, with the ball after AWAY's basket, is charged a technical that the
    feed records with neither a team nor a person; ``violation`` is the team of
    a delay-of-game violation recorded at the same clock, ``shooters`` the teams
    of the technical free throws there."""
    events = [e("make", 600, AWAY, 11)]
    if violation is not None:
        events.append(e("timeout", 590, violation, 0))
    events.append(e("foul", 590, 0, 0, subtype=subtype))
    events += [
        e("ft", 590, team, 11 if team == AWAY else 1, category="Technical", attempt=1,
          total=1, made=True)
        for team in shooters
    ]
    events.append(e("make", 570, HOME, 1))
    rows = encode_v3(wrap(events))
    for row in rows:
        if row["actionType"] == "Timeout":
            row.update(actionType="Violation", subType="Delay Of Game", personId=0,
                       description="Delay of game Violation")
    number = lambda kind: next(r["actionNumber"] for r in rows if r["actionType"] == kind)
    return rows, number("Foul"), (number("Violation") if violation is not None else None)


@pytest.mark.parametrize("violation, subtype", [
    (None, "Delay Technical"),
    (HOME, "Delay Technical"),
    (None, "Technical"),
], ids=["no_violation", "violation_agrees", "technical"])
def test_teamless_technical_is_charged_to_the_team_that_did_not_shoot(violation, subtype):
    rows, foul, witness = delay_technical(violation, subtype=subtype)
    loaded = load(rows)
    technical = next(x for x in loaded.events if x.event_num == foul)
    assert (technical.team_id, technical.player1_id) == (HOME, 0)
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY]
    assert dict(
        code=TEAMLESS_TECHNICAL_VERSION, event_num=foul, team_id=HOME,
        basis="opponent_of_technical_free_throw_shooter",
        delay_of_game_violations=[witness] if witness else [],
    ) in loaded.diagnostics
    assert TEAMLESS_TECHNICAL_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("change, message", [
    # 0022100040 Q3 12:00: Memphis's delay-of-game warning and the Lakers' delay
    # technical share a clock, so a violation alone cannot name the team.
    (dict(violation=AWAY), "contradicts a recorded delay-of-game violation"),
    (dict(shooters=(AWAY, HOME)), "one recorded technical free-throw team"),
    (dict(shooters=()), "one recorded technical free-throw team"),
], ids=["violation_by_the_shooting_team", "both_teams_shoot", "no_free_throw"])
def test_teamless_technical_without_one_decisive_team_rejects(change, message):
    rows, _, _ = delay_technical(**change)
    with pytest.raises(V3DecodeError, match=message):
        load(rows)


def test_teamless_technical_rule_is_nba_only():
    rows, _, _ = delay_technical()
    with pytest.raises(V3DecodeError, match="requires a known team"):
        load(rows, game="1022500001")


def test_teamless_event_other_than_a_technical_still_rejects():
    rows, foul, _ = delay_technical()
    next(r for r in rows if r["actionNumber"] == foul)["subType"] = "Too Many Players Technical"
    with pytest.raises(V3DecodeError, match="requires a known team"):
        load(rows)


def excess_timeout(technical_team=HOME, free_throw=True):
    """HOME, with the ball after AWAY's basket, calls a timeout it does not have: a
    technical the feed records as ``technical_team``'s (0 for none) and a turnover
    it records with neither a team nor a person; AWAY shoots the technical free
    throw unless ``free_throw`` is False, and scores."""
    events = [
        e("make", 600, AWAY, 11),
        e("foul", 590, technical_team, technical_team, subtype="Excess Timeout Technical"),
        e("turnover", 590, 0, 0, subtype="Excess Timeout Turnover"),
    ]
    if free_throw:
        events.append(
            e("ft", 590, AWAY, 11, category="Technical", attempt=1, total=1, made=True)
        )
    rows = encode_v3(wrap(events + [e("make", 570, AWAY, 12)]))
    number = lambda kind: next(r["actionNumber"] for r in rows if r["actionType"] == kind)
    return rows, number("Foul"), number("Turnover")


@pytest.mark.parametrize("technical_team", [HOME, 0], ids=["technical_names_team", "both_teamless"])
def test_teamless_excess_timeout_is_charged_to_the_team_that_did_not_shoot(technical_team):
    rows, technical, turnover = excess_timeout(technical_team)
    loaded = load(rows)
    for event in (technical, turnover):
        decoded = next(x for x in loaded.events if x.event_num == event)
        assert (decoded.team_id, decoded.player1_id) == (HOME, 0)
    assert next(x for x in loaded.events if x.event_num == turnover).is_possession_ending_event
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    rules = [d for d in loaded.diagnostics if d["code"] == TEAMLESS_EXCESS_TIMEOUT_VERSION]
    assert dict(
        code=TEAMLESS_EXCESS_TIMEOUT_VERSION, event_num=turnover, team_id=HOME,
        basis="opponent_of_technical_free_throw_shooter",
        recorded_team_events=[technical] if technical_team else [],
    ) in rules
    assert len(rules) == (1 if technical_team else 2)
    assert TEAMLESS_EXCESS_TIMEOUT_VERSION in loaded.capabilities["extensions"]
    assert TEAMLESS_TECHNICAL_VERSION not in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("change, message", [
    (dict(technical_team=AWAY), "contradicts its recorded technical or turnover"),
    (dict(free_throw=False), "one recorded technical free-throw team"),
], ids=["technical_names_the_shooting_team", "no_free_throw"])
def test_teamless_excess_timeout_without_one_decisive_team_rejects(change, message):
    rows, _, _ = excess_timeout(**change)
    with pytest.raises(V3DecodeError, match=message):
        load(rows)


def test_teamless_excess_timeout_rule_is_nba_only():
    rows, _, _ = excess_timeout()
    with pytest.raises(V3DecodeError, match="requires a known team"):
        load(rows, game="1022500001")


@pytest.mark.parametrize("game, technicals", [
    # Q1 3:48 after Gobert's offensive foul and Q4 12:00, each with no
    # violation: Powell, then Ingles, shot the technical free throw.
    ("0021900291", {84: (UTA, []), 683: (TOR, [])}),
    # Q2 2:31: Oklahoma City's delay-of-game violation, then Lillard's free throw.
    ("0021900341", {325: (OKC, [324])}),
    # Q1 3:02: Philadelphia's technical after its too-many-players turnover.
    ("0021900620", {116: (PHI, [])}),
    # Q2 12:00: Cleveland's delay technical, listed after the period's start.
    ("0021900682", {157: (CLE, [])}),
])
def test_recorded_2019_20_team_technicals(game, technicals):
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    assert game not in web.REVIEWED_CORRECTIONS
    loader = web.load_game(game, pbp, box, "recorded")
    for event, (team, violations) in technicals.items():
        technical = next(x for x in loader.events if x.event_num == event)
        assert (technical.team_id, technical.player1_id) == (team, 0)
        assert dict(
            code=TEAMLESS_TECHNICAL_VERSION, event_num=event, team_id=team,
            basis="opponent_of_technical_free_throw_shooter",
            delay_of_game_violations=violations,
        ) in loader.diagnostics
    assert len([d for d in loader.diagnostics if d["code"] == TEAMLESS_TECHNICAL_VERSION]) == len(technicals)
    assert TEAMLESS_TECHNICAL_VERSION in loader.capabilities["extensions"]
