"""Versioned rules for NBA 2026-27 V3 labels: defensive three seconds free throws and transition take fouls."""

import hashlib
import json

import pytest

from pbpstats.data_loader.stats_nba.possessions.loader import (
    TeamHasBackToBackPossessionsException,
)
from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader, V3Context, web
from pbpstats.data_loader.stats_nba_v3.decoder import (
    DEFENSIVE_THREE_SECOND_FT_VERSION,
    FOULS,
    TRANSITION_TAKE_FOUL_VERSION,
)
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, e, encode_v3, wrap

DATA = ROOT / "tests/parity/data/recorded_evidence"
POR, PHX = 1610612757, 1610612756


def load(rows, game="0022600001", validate_possessions=True):
    source = json.dumps({"game": {"gameId": game, "actions": rows}}).encode()
    roster = {
        p: {"team_id": team, "names": [f"Player{p}"]}
        for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for p in players
    }
    context = V3Context(
        game, (HOME, AWAY), roster,
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Controlled label-rule context", hashlib.sha256(source).hexdigest(),
    )
    return StatsNbaV3PossessionLoader(source, context, validate_possessions=validate_possessions)


def number(rows, kind):
    return next(r["actionNumber"] for r in rows if r["actionType"] == kind)


def defensive_three_seconds(and_one=False):
    """AWAY's defensive three seconds while HOME has the ball; HOME's one free
    throw is recorded as "Free Throw 1 of 1", and HOME keeps the ball and scores.
    ``and_one`` adds a HOME basket and an AWAY shooting foul at the same clock."""
    events = [e("make", 600, AWAY, 11)]
    if and_one:
        events += [e("make", 590, HOME, 2), e("foul", 590, AWAY, 13, subtype="Shooting")]
    events += [
        e("foul", 590, AWAY, 12, subtype="Defense 3 Second"),
        e("ft", 590, HOME, 1, attempt=1, total=1, made=True),
        e("make", 570, HOME, 3),
        e("make", 550, AWAY, 11),
    ]
    rows = encode_v3(wrap(events))
    return rows, number(rows, "Free Throw"), next(
        r["actionNumber"] for r in rows if r["subType"] == "Defense 3 Second"
    )


def test_defensive_three_seconds_one_of_one_is_its_technical_free_throw():
    rows, ft, foul = defensive_three_seconds()
    loaded = load(rows)
    free_throw = next(x for x in loaded.events if x.event_num == ft)
    assert free_throw.event_action_type == 16 and free_throw.is_technical_ft
    assert free_throw.description == "Player1 Free Throw Technical (1 PTS)"
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    assert dict(
        code=DEFENSIVE_THREE_SECOND_FT_VERSION, event_num=ft, foul_event_num=foul,
        recorded="Free Throw 1 of 1", decoded="Free Throw Technical",
    ) in loaded.diagnostics
    assert DEFENSIVE_THREE_SECOND_FT_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("game, and_one", [
    ("0022600001", True),
    ("1022600001", False),
], ids=["another_foul_at_the_clock", "wnba"])
def test_defensive_three_seconds_rule_leaves_other_one_of_ones(game, and_one):
    rows, ft, _ = defensive_three_seconds(and_one)
    loaded = load(rows, game, validate_possessions=False)
    assert next(x for x in loaded.events if x.event_num == ft).event_action_type == 10
    assert not any(d["code"] == DEFENSIVE_THREE_SECOND_FT_VERSION for d in loaded.diagnostics)


def take_foul(text="(P1.T2)", attempts=1):
    """AWAY's take foul on HOME, outside the penalty unless ``text`` says so,
    with ``attempts`` HOME free throws; HOME keeps the ball and scores."""
    events = [
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 12, subtype="Personal Take"),
    ] + [
        e("ft", 590, HOME, 1, attempt=attempt, total=attempts, made=True)
        for attempt in range(1, attempts + 1)
    ] + [e("make", 570, HOME, 3), e("make", 550, AWAY, 11)]
    rows = encode_v3(wrap(events))
    foul = next(r for r in rows if r["actionType"] == "Foul")
    foul["description"] = f"Player12 Personal Take Foul {text} (J.Doe)"
    return rows, foul["actionNumber"], number(rows, "Free Throw")


def test_personal_take_with_one_free_throw_is_a_transition_take_foul():
    rows, foul, ft = take_foul()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows, game="1022600001")
    loaded = load(rows)
    take = next(x for x in loaded.events if x.event_num == foul)
    assert take.event_action_type == FOULS["Transition Take"] and take.is_transition_take_foul
    assert next(x for x in loaded.events if x.event_num == ft).is_transition_take_foul_ft
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    assert dict(
        code=TRANSITION_TAKE_FOUL_VERSION, event_num=foul, free_throw_event_num=ft,
        recorded="Personal Take", decoded="Transition Take",
    ) in loaded.diagnostics
    assert TRANSITION_TAKE_FOUL_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("text, attempts", [
    # 0022400814 Q4 0:06.9 and three earlier games: a take foul in the penalty,
    # its one recorded free throw coded a personal take in V2.
    ("(P5.PN)", 1),
    ("(P1.T2)", 2),
], ids=["in_the_penalty", "two_free_throws"])
def test_take_foul_rule_leaves_other_personal_take_fouls(text, attempts):
    rows, foul, _ = take_foul(text, attempts)
    loaded = load(rows, validate_possessions=False)
    assert next(x for x in loaded.events if x.event_num == foul).event_action_type == (
        FOULS["Personal Take"]
    )
    assert not any(d["code"] == TRANSITION_TAKE_FOUL_VERSION for d in loaded.diagnostics)


def test_recorded_2026_27_labels_decode_without_review():
    # 0022600092: Maluach's (Q1 7:32) and Krejci's (Q4 4:38) take fouls, and the
    # free throws for Williams III's (Q1 2:47) and Clingan's (Q3 7:51) defensive
    # three seconds.
    game = "0022600092"
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    assert game not in web.REVIEWED_CORRECTIONS
    loader = web.load_game(game, pbp, box, "recorded")
    rules = [
        (d["code"], d["event_num"]) for d in loader.diagnostics
        if d["code"] in (DEFENSIVE_THREE_SECOND_FT_VERSION, TRANSITION_TAKE_FOUL_VERSION)
    ]
    assert rules == [
        (TRANSITION_TAKE_FOUL_VERSION, 52),
        (DEFENSIVE_THREE_SECOND_FT_VERSION, 151),
        (DEFENSIVE_THREE_SECOND_FT_VERSION, 422),
        (TRANSITION_TAKE_FOUL_VERSION, 686),
    ]
    assert loader.counts_by_team == {POR: 97, PHX: 96}
    rows = json.loads(pbp)["game"]["actions"]
    assert sorted(i for x in loader.events for i in x.v3_source_indices) == list(range(len(rows)))
