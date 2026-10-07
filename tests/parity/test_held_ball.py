"""Held-ball turnover extension: the original's same-clock jump-ball rule at a later clock."""

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
from pbpstats.data_loader.stats_nba_v3.overrides import CHANGE_EVENTS, KEEP_EVENTS
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, e, encode_v3, wrap

GAME = "0022500001"
DATA = ROOT / "tests/parity/data/recorded_evidence"
DISABLED = "pbpstats.data_loader.stats_nba_v3.possessions.is_candidate"


def held_ball(turnover_clock, tip_team=AWAY, turnover_team=HOME, opening=False):
    """HOME has the ball; a jump ball; a recorded turnover with a steal; a make."""
    other = AWAY if turnover_team == HOME else HOME
    events = [] if opening else [e("make", 600, AWAY, 11)]
    events += [
        e("jump", 720 if opening else 590, HOME, 1, opponent=11,
          winner_team=tip_team, winner=12 if tip_team == AWAY else 2),
        e("turnover", turnover_clock, turnover_team, 1 if turnover_team == HOME else 11,
          subtype="Lost Ball"),
        e("make", 580, other, 13 if other == AWAY else 3),
    ]
    rows = encode_v3(wrap(events))
    turnover = next(r for r in rows if r["actionType"] == "Turnover")
    stealer = 11 if other == AWAY else 1
    rows.insert(rows.index(turnover) + 1, dict(
        turnover, actionId=99, actionType="", subType="", personId=stealer, teamId=other,
        location="v" if other == AWAY else "h", description=f"Player{stealer} STEAL (1 STL)",
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
        turnover_clock="9:47", tip_team_id=AWAY, turnover_team_id=HOME,
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
    with patch(DISABLED, lambda event, following: False):
        assert outcome(held_ball(587)) == "TeamHasBackToBackPossessionsException"


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
], ids=["winner_turnover", "opening_tip"])
def test_other_jump_ball_turnovers_keep_original_decisions(rows):
    expected = outcome(rows)
    with patch(DISABLED, lambda event, following: False):
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
    with patch(DISABLED, lambda event, following: False):
        with pytest.raises(TeamHasBackToBackPossessionsException):
            web.load_game("0022500165", pbp, box, "recorded")
