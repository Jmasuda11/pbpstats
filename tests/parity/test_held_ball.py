"""Held-ball turnover extension: the original's same-clock jump-ball rule at the recorded turnover."""

import hashlib
import json
from unittest.mock import patch

import pytest

from pbpstats.data_loader.stats_nba.possessions.loader import (
    TeamHasBackToBackPossessionsException,
)
from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3Context,
    V3Overrides,
    web,
)
from pbpstats.data_loader.stats_nba_v3.held_ball import (
    HELD_BALL_VERSION,
    V3HeldBallJumpBall,
)
from pbpstats.resources.enhanced_pbp import Substitution
from pbpstats.data_loader.stats_nba_v3.overrides import CHANGE_EVENTS, KEEP_EVENTS
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, e, encode_v3, wrap

GAME = "0022500001"
DATA = ROOT / "tests/parity/data/recorded_evidence"
DISABLED = "pbpstats.data_loader.stats_nba_v3.possessions.is_candidate_at"
ORIGINAL = lambda items, index: False


def held_ball(turnover_clock, tip_team=AWAY, turnover_team=HOME, opening=False,
              substitution=None, steal=False):
    """HOME has the ball; a jump ball; a recorded turnover with a steal; a make.

    ``substitution`` logs HOME's Player6 for Player3 at that clock, between the
    jump ball and the turnover. ``steal`` first has AWAY's Player11 strip
    HOME's Player1 at the jump ball's clock, just before the tip.
    """
    other = AWAY if turnover_team == HOME else HOME
    events = [] if opening else [e("make", 600, AWAY, 11)]
    if steal:
        events.append(e("turnover", 590, HOME, 1, subtype="Lost Ball"))
    events += [
        e("jump", 720 if opening else 590, HOME, 1, opponent=11,
          winner_team=tip_team, winner=12 if tip_team == AWAY else 2),
        *([e("sub", substitution, HOME, 3, incoming=6)] if substitution is not None else []),
        e("turnover", turnover_clock, turnover_team, 1 if turnover_team == HOME else 11,
          subtype="Lost Ball"),
        e("make", 580, other, 13 if other == AWAY else 3),
    ]
    rows = encode_v3(wrap(events))
    for action_id, turnover in zip((99, 98), [r for r in rows if r["actionType"] == "Turnover"]):
        team = AWAY if turnover["teamId"] == HOME else HOME
        stealer = 11 if team == AWAY else 1
        rows.insert(rows.index(turnover) + 1, dict(
            turnover, actionId=action_id, actionType="", subType="", personId=stealer,
            teamId=team, location="v" if team == AWAY else "h",
            description=f"Player{stealer} STEAL (1 STL)",
        ))
    return rows


def load(rows, overrides=None):
    source = json.dumps({"game": {"gameId": GAME, "actions": rows}}).encode()
    roster = {
        p: {"team_id": team, "names": [f"Player{p}"]}
        for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for p in players
    }
    context = V3Context(
        GAME, (HOME, AWAY), roster,
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Controlled held-ball context", hashlib.sha256(source).hexdigest(),
    )
    if overrides is not None:
        overrides = V3Overrides(
            {name: json.dumps({GAME: numbers}).encode() for name, numbers in overrides.items()},
            "Controlled review", hashlib.sha256(source).hexdigest(),
        )
    return StatsNbaV3PossessionLoader(source, context, overrides=overrides)


def outcome(rows):
    try:
        loaded = load(rows)
    except TeamHasBackToBackPossessionsException:
        return "TeamHasBackToBackPossessionsException"
    return [(p.offense_team_id, [x.event_num for x in p.events]) for p in loaded.items]


def credits(loaded):
    return sorted(
        (s["player_id"], s["stat_key"], s["stat_value"], s["lineup_id"])
        for s in loaded.base_stats
        if s["stat_key"] in ("OffPoss", "DefPoss")
    )


def test_later_turnover_by_the_team_that_lost_the_tip_ends_its_possession():
    loaded = load(held_ball(587))
    jump, turnover = (x for x in loaded.events if x.event_type in (10, 5))
    assert isinstance(jump, V3HeldBallJumpBall)
    assert jump.held_ball_turnover is turnover
    assert not jump.is_possession_ending_event and turnover.is_possession_ending_event
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    held = loaded.items[1]
    assert held.events == [jump, turnover] and held.end_time == "9:47"
    assert loaded.items[2].start_time == "9:47"
    assert turnover.count_as_possession and turnover.player3_id == 11
    assert loaded.capabilities["extensions"] == [HELD_BALL_VERSION]
    assert [d for d in loaded.diagnostics if d["code"] == HELD_BALL_VERSION] == [dict(
        code=HELD_BALL_VERSION, event_num=jump.event_num,
        turnover_event_num=turnover.event_num, period=1, jump_ball_clock="9:50",
        substitution_event_nums=[], steal_turnover_event_num=None, turnover_clock="9:47",
        tip_team_id=AWAY, turnover_team_id=HOME,
        basis="original_same_clock_jump_ball_turnover_rule_at_recorded_turnover",
    )]


def test_extension_reproduces_the_original_same_clock_decisions():
    later, same = load(held_ball(587)), load(held_ball(590))
    assert not any(isinstance(x, V3HeldBallJumpBall) for x in same.events)
    assert "extensions" not in same.capabilities
    assert [(p.offense_team_id, [x.event_num for x in p.events]) for p in later.items] == [
        (p.offense_team_id, [x.event_num for x in p.events]) for p in same.items
    ]
    assert credits(later) == credits(same)


def test_original_alone_fails_its_alternation_check():
    with patch(DISABLED, ORIGINAL):
        assert outcome(held_ball(587)) == "TeamHasBackToBackPossessionsException"
        assert outcome(held_ball(587, substitution=590)) == (
            "TeamHasBackToBackPossessionsException"
        )


def test_stoppage_substitution_between_the_jump_ball_and_its_turnover():
    loaded = load(held_ball(587, substitution=590))
    jump, substitution, turnover = (x for x in loaded.events if x.event_type in (10, 8, 5))
    assert isinstance(jump, V3HeldBallJumpBall) and isinstance(substitution, Substitution)
    assert jump.stoppage_substitutions == [substitution]
    assert jump.held_ball_turnover is turnover
    assert not jump.is_possession_ending_event and turnover.is_possession_ending_event
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    held = loaded.items[1]
    assert held.events == [jump, substitution, turnover] and held.end_time == "9:47"
    assert loaded.items[2].start_time == "9:47"
    assert loaded.capabilities["extensions"] == [HELD_BALL_VERSION]
    assert [(d["event_num"], d["substitution_event_nums"], d["turnover_event_num"])
            for d in loaded.diagnostics if d["code"] == HELD_BALL_VERSION] == [
        (jump.event_num, [substitution.event_num], turnover.event_num)
    ]


def test_same_clock_turnover_past_a_substitution_gets_the_same_clock_decisions():
    # The original decides a turnover right after the jump ball at its clock;
    # with the substitution logged between them, the extension decides it alike.
    plain, logged = load(held_ball(590)), load(held_ball(590, substitution=590))
    assert not any(isinstance(x, V3HeldBallJumpBall) for x in plain.events)
    jump = next(x for x in logged.events if x.event_type == 10)
    assert isinstance(jump, V3HeldBallJumpBall) and jump.held_ball_turnover is not None

    def shape(loaded):
        return [(p.offense_team_id, [x.event_type for x in p.events if x.event_type != 8])
                for p in loaded.items]

    assert shape(logged) == shape(plain)
    with patch(DISABLED, ORIGINAL):
        assert outcome(held_ball(590, substitution=590)) == (
            "TeamHasBackToBackPossessionsException"
        )


def test_held_ball_on_the_player_who_just_stole_the_ball():
    # HOME loses the ball to AWAY's steal; the stealer is tied up at once and
    # HOME wins the tip; AWAY is charged with the held ball two seconds later.
    loaded = load(held_ball(588, tip_team=HOME, turnover_team=AWAY, steal=True))
    steal, turnover = (x for x in loaded.events if x.event_type == 5)
    jump = next(x for x in loaded.events if x.event_type == 10)
    assert isinstance(jump, V3HeldBallJumpBall)
    assert jump.steal_turnover is steal and jump.held_ball_turnover is turnover
    assert steal.is_possession_ending_event and not jump.is_possession_ending_event
    # The last possession holds only the end of the period.
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME, AWAY]
    assert loaded.items[2].events == [jump, turnover]
    assert (loaded.items[2].start_time, loaded.items[2].end_time) == ("9:50", "9:48")
    assert [(d["event_num"], d["steal_turnover_event_num"], d["turnover_event_num"])
            for d in loaded.diagnostics if d["code"] == HELD_BALL_VERSION] == [
        (jump.event_num, steal.event_num, turnover.event_num)
    ]
    with patch(DISABLED, ORIGINAL):
        assert outcome(held_ball(588, tip_team=HOME, turnover_team=AWAY, steal=True)) == (
            "TeamHasBackToBackPossessionsException"
        )


def test_substitution_at_another_clock_is_not_skipped():
    # A substitution after the tip needs another stoppage, so the turnover
    # past it is not the held ball's.
    rows = held_ball(587, substitution=588)
    expected = outcome(rows)
    with patch(DISABLED, ORIGINAL):
        assert outcome(rows) == expected
    if expected != "TeamHasBackToBackPossessionsException":
        assert not any(d["code"] == HELD_BALL_VERSION for d in load(rows).diagnostics)


@pytest.mark.parametrize("override", [CHANGE_EVENTS, KEEP_EVENTS])
def test_reviewed_possession_overrides_keep_precedence(override):
    # Neither original override file can express the held ball: marking the
    # jump ball possession-neutral still leaves its winner on offense.
    rows = held_ball(587)
    jump = next(r for r in rows if r["actionType"] == "Jump Ball")["actionNumber"]
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows, overrides={override: [jump]})


@pytest.mark.parametrize("rows", [
    held_ball(587, turnover_team=AWAY),  # the winner's own later turnover
    held_ball(700, opening=True),  # the period's opening tip
    held_ball(588, tip_team=AWAY, turnover_team=AWAY, steal=True),  # the stealer's team wins
], ids=["winner_turnover", "opening_tip", "stealer_wins_tip"])
def test_other_jump_ball_turnovers_keep_original_decisions(rows):
    expected = outcome(rows)
    with patch(DISABLED, ORIGINAL):
        assert outcome(rows) == expected
    if expected != "TeamHasBackToBackPossessionsException":
        loaded = load(rows)
        assert not any(d["code"] == HELD_BALL_VERSION for d in loaded.diagnostics)
        assert HELD_BALL_VERSION not in loaded.capabilities.get("extensions", [])


def test_recorded_held_ball_ends_the_bucks_possession_at_the_turnover():
    pbp = (DATA / "stats_v3_0022500165.json").read_bytes()
    box = (DATA / "stats_v3_boxscore_0022500165.json").read_bytes()
    loader = web.load_game("0022500165", pbp, box, "recorded")
    bucks, raptors = 1610612749, 1610612761
    # Q1 8:32 "Jump Ball Barrett vs. Rollins: Tip to Ingram"; 8:29 "Rollins Lost
    # Ball Turnover" with "Barrett STEAL". The original raises at the turnover.
    jump = next(x for x in loader.events if x.event_num == 44)
    assert isinstance(jump, V3HeldBallJumpBall)
    assert jump.held_ball_turnover.event_num == 47
    index = next(i for i, p in enumerate(loader.items) if jump in p.events)
    held, following = loader.items[index], loader.items[index + 1]
    assert [x.event_num for x in held.events] == [44, 47]
    assert held.offense_team_id == bucks
    assert (held.start_time, held.end_time) == ("8:40", "8:29")
    assert following.offense_team_id == raptors and following.start_time == "8:29"
    assert [(d["event_num"], d["turnover_event_num"]) for d in loader.diagnostics
            if d["code"] == HELD_BALL_VERSION] == [(44, 47)]
    assert loader.counts_by_team == {raptors: 99, bucks: 98}
    with patch(DISABLED, ORIGINAL):
        with pytest.raises(TeamHasBackToBackPossessionsException):
            web.load_game("0022500165", pbp, box, "recorded")


def test_recorded_substitution_between_the_jump_ball_and_the_suns_turnover():
    pbp = (DATA / "stats_v3_0022500088.json").read_bytes()
    box = (DATA / "stats_v3_boxscore_0022500088.json").read_bytes()
    loader = web.load_game("0022500088", pbp, box, "recorded")
    suns, kings = 1610612756, 1610612758
    # Q2 2:51 Brooks rebound; 2:38 "Jump Ball Booker vs. DeRozan: Tip to LaVine",
    # then "SUB: O'Neale FOR Dunn" at 2:38; 2:34 "Booker Lost Ball Turnover" with
    # "DeRozan STEAL"; 2:25 LaVine's three. The original raises at the three.
    jump = next(x for x in loader.events if x.event_num == 346)
    assert isinstance(jump, V3HeldBallJumpBall)
    assert [x.event_num for x in jump.stoppage_substitutions] == [344]
    assert jump.held_ball_turnover.event_num == 349
    index = next(i for i, p in enumerate(loader.items) if jump in p.events)
    held, following = loader.items[index], loader.items[index + 1]
    assert [x.event_num for x in held.events] == [346, 344, 349]
    assert held.offense_team_id == suns
    assert (held.start_time, held.end_time) == ("2:51", "2:34")
    assert following.offense_team_id == kings and following.start_time == "2:34"
    assert [x.event_num for x in following.events] == [351]
    assert [(d["event_num"], d["substitution_event_nums"], d["turnover_event_num"])
            for d in loader.diagnostics if d["code"] == HELD_BALL_VERSION] == [(346, [344], 349)]
    assert loader.counts_by_team == {suns: 101, kings: 100}
    with patch(DISABLED, ORIGINAL):
        with pytest.raises(TeamHasBackToBackPossessionsException):
            web.load_game("0022500088", pbp, box, "recorded")


def test_recorded_held_ball_on_the_wizards_stealer():
    pbp = (DATA / "stats_v3_0022500879.json").read_bytes()
    box = (DATA / "stats_v3_boxscore_0022500879.json").read_bytes()
    loader = web.load_game("0022500879", pbp, box, "recorded")
    rockets, wizards = 1610612745, 1610612764
    # Q3 11:23 "Sengun Lost Ball Turnover" with "Reese STEAL"; "Jump Ball Reese vs.
    # Sengun: Tip to Durant" at 11:23; 11:22 "Reese Lost Ball Turnover" with
    # "Sengun STEAL". Video review: Reese stole the ball and was tied up at once.
    jump = next(x for x in loader.events if x.event_num == 347)
    assert isinstance(jump, V3HeldBallJumpBall)
    assert jump.steal_turnover.event_num == 345
    assert jump.held_ball_turnover.event_num == 350
    index = next(i for i, p in enumerate(loader.items) if jump in p.events)
    before, held, after = loader.items[index - 1:index + 2]
    assert [x.event_num for x in before.events] == [345] and before.offense_team_id == rockets
    assert [x.event_num for x in held.events] == [347, 350] and held.offense_team_id == wizards
    assert (held.start_time, held.end_time) == ("11:23", "11:22")
    assert after.offense_team_id == rockets and after.start_time == "11:22"
    assert loader.counts_by_team == {rockets: 101, wizards: 102}
    with patch(DISABLED, ORIGINAL):
        with pytest.raises(TeamHasBackToBackPossessionsException):
            web.load_game("0022500879", pbp, box, "recorded")
