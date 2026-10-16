"""Reviewed corrections: the original's override files plus play-by-play edits, bound to exact bytes."""

import hashlib
import json
import re
from types import SimpleNamespace

import pytest

from pbpstats.data_loader.stats_nba.possessions.loader import (
    TeamHasBackToBackPossessionsException,
)
from pbpstats.resources.enhanced_pbp.start_of_period import (
    InvalidNumberOfStartersException,
)
from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3Context,
    V3DecodeError,
    V3JumpBallEvidence,
    V3Overrides,
    web,
)
from pbpstats.data_loader.stats_nba_v3.decoder import DecodedV3
from pbpstats.data_loader.stats_nba_v3.overrides import (
    EVENT_BLOCKS,
    EVENT_CLOCK_RESETS,
    EVENT_CLOCKS,
    EVENT_DUPLICATES,
    EVENT_FOUL_OPPONENTS,
    EVENT_LIVE_NUMBERS,
    EVENT_LOCATIONS,
    EVENT_MOVES,
    EVENT_ORDER,
    EVENT_REMOVALS,
    EVENT_SUBTYPES,
    EVENT_TEAMS,
    EVENT_TIP_RECIPIENTS,
    EVENT_TURNOVERS,
    SUPPORTED,
)
from pbpstats.data_loader.stats_nba_v3.team_heave import TEAM_HEAVE_VERSION, V3TeamHeave
from pbpstats.resources.enhanced_pbp import Turnover
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, e, encode_v3, wrap
from tools.parity.team_heave_cases import catalog as heave_cases, v3_inputs as heave_rows

GAME = "0022500001"
DATA = ROOT / "tests/parity/data/recorded_evidence"


def numbered(rows, kind, subtype=None):
    return next(
        r["actionNumber"] for r in rows
        if r["actionType"] == kind and (subtype is None or r["subType"] == subtype)
    )


def technical_after_last_free_throw():
    """HOME is fouled; AWAY's technical comes during free throw 2, whose attempt
    is shot again after the technical free throw; the feed lists the technical
    free throw after free throw 2."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 11, subtype="Shooting"),
        e("ft", 590, HOME, 1, attempt=1, total=2, made=True),
        e("foul", 590, AWAY, 12, subtype="Technical"),
        e("ft", 590, HOME, 1, attempt=2, total=2, made=True),
        e("ft", 590, HOME, 3, category="Technical", attempt=1, total=1, made=True),
        e("make", 570, AWAY, 13),
    ]))
    return rows, dict(
        second=numbered(rows, "Free Throw", "Free Throw 2 of 2"),
        technical=numbered(rows, "Free Throw", "Free Throw Technical"),
    )


def violation_on_second_free_throw():
    """HOME's second free throw ends in its own lane violation; the feed logs the
    made first free throw as 1 of 1, the league's label when one attempt counts."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 11, subtype="Shooting"),
        e("ft", 590, HOME, 1, attempt=1, total=1, made=True),
        e("turnover", 590, HOME, 2, subtype="Lane Violation"),
        e("make", 570, AWAY, 13),
    ]))
    return rows, numbered(rows, "Free Throw")


def edits(name, values):
    return {name: json.dumps({GAME: values}).encode()}


def load(rows, moves=None, files=None):
    source = json.dumps({"game": {"gameId": GAME, "actions": rows}}).encode()
    roster = {
        p: {"team_id": team, "names": [f"Player{p}"]}
        for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for p in players
    }
    context = V3Context(
        GAME, (HOME, AWAY), roster,
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Controlled correction context", hashlib.sha256(source).hexdigest(),
    )
    if moves is not None:
        files = edits(EVENT_ORDER, moves)
    overrides = (
        V3Overrides(files, "Controlled review", hashlib.sha256(source).hexdigest())
        if files is not None else None
    )
    return StatsNbaV3PossessionLoader(source, context, overrides=overrides)


def offenses(loaded):
    return [p.offense_team_id for p in loaded.items]


def test_event_order_edit_restores_the_free_throw_trip():
    rows, n = technical_after_last_free_throw()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, moves=[[n["technical"], n["second"]]])
    numbers = [x.event_num for x in loaded.events]
    assert numbers.index(n["technical"]) + 1 == numbers.index(n["second"])
    trip = next(p for p in loaded.items if any(x.event_num == n["second"] for x in p.events))
    assert trip.offense_team_id == HOME and trip.events[-1].event_num == n["second"]
    assert offenses(loaded)[:4] == [AWAY, HOME, AWAY, HOME]
    assert dict(code="reviewed_event_order", moves=[[n["technical"], n["second"]]]) in loaded.diagnostics
    assert [d["file"] for d in loaded.diagnostics if d["code"] == "recorded_override_input"] == [EVENT_ORDER]


@pytest.mark.parametrize("moves, message", [
    ([[999, 1]], "names an event not in the source"),
    ("move", "Invalid event-order override move"),
    ([[5]], "Invalid event-order override move"),
    ([[5, 5]], "Invalid event-order override move"),
    ([[-1, 5]], "Invalid event-order override move"),
], ids=["unknown_event", "not_a_list", "not_a_pair", "same_event", "negative"])
def test_event_order_edits_are_validated(moves, message):
    rows, n = technical_after_last_free_throw()
    with pytest.raises(V3DecodeError, match=message):
        load(rows, moves=moves)


def test_event_order_edit_stays_within_one_clock():
    rows, n = technical_after_last_free_throw()
    later = next(r["actionNumber"] for r in rows if r["clock"] == "PT9M30S")
    with pytest.raises(V3DecodeError, match="moves an event to another clock"):
        load(rows, moves=[[later, n["second"]]])


def test_free_throw_subtype_edit_ends_the_trip_at_the_violation():
    rows, ft = violation_on_second_free_throw()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, files=edits(EVENT_SUBTYPES, {str(ft): "Free Throw 1 of 2"}))
    throw = next(x for x in loaded.events if x.event_num == ft)
    assert throw.is_ft_1_of_2 and not throw.is_possession_ending_event
    assert "Free Throw 1 of 2" in throw.description
    assert throw.free_throw_type == "2pt Shooting Foul"
    trip = next(p for p in loaded.items if throw in p.events)
    assert trip.offense_team_id == HOME and isinstance(trip.events[-1], Turnover)
    assert offenses(loaded)[:4] == [AWAY, HOME, AWAY, HOME]
    assert dict(code="reviewed_event_subtype", event_num=ft, recorded="Free Throw 1 of 1",
                reviewed="Free Throw 1 of 2") in loaded.diagnostics


def test_turnover_subtype_edit_makes_the_turnover_count():
    # A blank turnover subtype is V2 code 0, the original's no-turnover.
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 11, subtype="Shooting"),
        e("ft", 590, HOME, 1, attempt=1, total=2, made=True),
        e("turnover", 590, HOME, 2, subtype=""),
        e("make", 570, AWAY, 13),
    ]))
    turnover = numbered(rows, "Turnover")
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, files=edits(EVENT_SUBTYPES, {str(turnover): "Lane Violation"}))
    event = next(x for x in loaded.events if x.event_num == turnover)
    assert event.is_lane_violation and not event.is_no_turnover and event.is_possession_ending_event
    assert offenses(loaded)[:4] == [AWAY, HOME, AWAY, HOME]


def test_foul_subtype_edit_ends_the_trip_after_penalty_free_throws():
    # The original keeps possession after an away-from-play foul's free throws.
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 11, subtype="Away From Play"),
        e("ft", 590, HOME, 1, attempt=1, total=2, made=True),
        e("ft", 590, HOME, 1, attempt=2, total=2, made=True),
        e("make", 570, AWAY, 13),
    ]))
    foul = numbered(rows, "Foul")
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, files=edits(EVENT_SUBTYPES, {str(foul): "Personal"}))
    second = next(x for x in loaded.events if x.event_num == foul + 2)
    assert second.is_possession_ending_event and second.free_throw_type == "Penalty"
    assert offenses(loaded)[:4] == [AWAY, HOME, AWAY, HOME]


def test_rebound_subtype_edit_makes_a_real_team_rebound():
    # "Normal Rebound" is V2's placeholder code: a defensive team rebound typed
    # so after a missed last free throw does not change possession.
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 11, subtype="Shooting"),
        e("ft", 590, HOME, 1, attempt=1, total=2, made=True),
        e("ft", 590, HOME, 1, attempt=2, total=2, made=False),
        e("rebound", 590, AWAY, 0),
        e("make", 570, AWAY, 13),
    ]))
    rebound = numbered(rows, "Rebound")
    next(r for r in rows if r["actionNumber"] == rebound)["subType"] = "Normal Rebound"
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, files=edits(EVENT_SUBTYPES, {str(rebound): "Unknown"}))
    event = next(x for x in loaded.events if x.event_num == rebound)
    assert event.is_real_rebound and event.is_possession_ending_event
    assert offenses(loaded)[:4] == [AWAY, HOME, AWAY, HOME]


@pytest.mark.parametrize("labels, message", [
    ({"ft": "Free Throw 4 of 2"}, "does not fit the recorded event"),
    ({"ft": "Personal"}, "does not fit the recorded event"),
    ({"999": "Free Throw 1 of 2"}, "does not fit the recorded event"),
    ({"ft": ""}, "Invalid event subtype override"),
    (["ft"], "Invalid event subtype override"),
], ids=["no_such_label", "other_kind_label", "unknown_event", "blank", "not_a_map"])
def test_subtype_edits_are_validated(labels, message):
    rows, ft = violation_on_second_free_throw()
    if isinstance(labels, dict):
        labels = {str(ft) if key == "ft" else key: value for key, value in labels.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_SUBTYPES, labels))


def and_one_a_tenth_later():
    rows = encode_v3(wrap([
        e("make", 40, AWAY, 11),
        e("make", "19.4", HOME, 1),
        e("foul", "19.3", AWAY, 11, subtype="Shooting"),
        e("ft", "19.3", HOME, 1, attempt=1, total=1, made=False),
        e("rebound", "19.3", AWAY, 12),
        e("make", 5, AWAY, 13),
    ]))
    return rows, numbered(rows, "Foul"), numbered(rows, "Free Throw")


def test_clock_edit_restores_an_and_one():
    rows, foul, ft = and_one_a_tenth_later()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, files=edits(EVENT_CLOCKS, {str(foul): "PT00M19.40S", str(ft): "PT00M19.40S"}))
    throw = next(x for x in loaded.events if x.event_num == ft)
    assert throw.clock == "0:19.4" and throw.free_throw_type == "2pt And 1"
    trip = next(p for p in loaded.items if throw in p.events)
    assert trip.offense_team_id == HOME and trip.events[-1].event_num == ft + 1
    assert dict(code="reviewed_event_clock", event_num=foul, recorded="0:19.3",
                reviewed="0:19.4") in loaded.diagnostics


@pytest.mark.parametrize("values, message", [
    ({"foul": "PT00M21.40S"}, "moves an event more than two seconds"),
    ({"foul": "PT00M19.80S"}, "breaks the recorded order"),
    ({"999": "PT00M19.40S"}, "names an event not in the source"),
    ({"foul": "0:19.4"}, "Invalid event clock override"),
], ids=["over_two_seconds", "breaks_order", "unknown_event", "not_a_v3_clock"])
def test_clock_edits_are_validated(values, message):
    rows, foul, ft = and_one_a_tenth_later()
    values = {str(foul) if key == "foul" else key: value for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_CLOCKS, values))


def rebound_twice():
    """HOME rebounds its own miss as a team, a rebound the feed records twice."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("miss", 590, HOME, 1),
        e("rebound", 590, HOME, 0),
        e("rebound", 590, HOME, 0),
        e("make", 570, HOME, 2),
    ]))
    first, second = (r["actionNumber"] for r in rows if r["actionType"] == "Rebound")
    return rows, dict(miss=numbered(rows, "Missed Shot"), first=first, second=second)


def test_duplicate_edit_drops_a_rebound_recorded_twice():
    rows, n = rebound_twice()
    # The original attaches one rebound to a miss; its repairs then need data.nba.com.
    with pytest.raises(V3DecodeError, match="additional recorded provider evidence"):
        load(rows)
    loaded = load(rows, files=edits(EVENT_DUPLICATES, {str(n["first"]): n["second"]}))
    trip = next(p for p in loaded.items if any(x.event_num == n["miss"] for x in p.events))
    assert [x.event_num for x in trip.events] == [n["miss"], n["second"], n["second"] + 1]
    assert trip.offense_team_id == HOME and trip.events[1].oreb
    assert dict(code="reviewed_duplicate_event", event_num=n["first"],
                kept=n["second"]) in loaded.diagnostics
    # The dropped copy's row belongs to the rebound kept, so every row still
    # belongs to exactly one event.
    index = {r["actionNumber"]: i for i, r in enumerate(rows)}
    assert trip.events[1].v3_source_indices == (index[n["first"]], index[n["second"]])
    assert sorted(i for x in loaded.events for i in x.v3_source_indices) == list(range(len(rows)))


@pytest.mark.parametrize("values, message", [
    ({"first": 999}, "does not keep a recorded copy"),
    ({"first": "second", "second": "first"}, "does not keep a recorded copy"),
    ({"miss": "first"}, "names events that differ"),
    ({"first": "first"}, "Invalid event duplicate override"),
    ({"first": "kept"}, "Invalid event duplicate override"),
], ids=["unknown_copy", "both_dropped", "different_events", "itself", "not_an_event"])
def test_duplicate_edits_are_validated(values, message):
    rows, n = rebound_twice()
    values = {str(n.get(key, key)): n.get(value, value) for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_DUPLICATES, values))


def missed_and_rebounded(blocked=False):
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("miss", 590, HOME, 1),
        e("rebound", 589, AWAY, 12),
        e("make", 570, AWAY, 13),
    ]))
    if blocked:
        index = next(i for i, r in enumerate(rows) if r["actionType"] == "Missed Shot")
        rows.insert(index + 1, dict(
            rows[index], actionId=99, actionType="", subType="", personId=11,
            teamId=AWAY, location="v", description="Player11 BLOCK (1 BLK)",
        ))
    return rows, dict(miss=numbered(rows, "Missed Shot"), make=numbered(rows, "Made Shot"))


def test_block_edit_records_the_blocker_v3_omits():
    rows, n = missed_and_rebounded()
    assert not next(x for x in load(rows).events if x.event_num == n["miss"]).is_blocked
    loaded = load(rows, files=edits(EVENT_BLOCKS, {str(n["miss"]): 11}))
    shot = next(x for x in loaded.events if x.event_num == n["miss"])
    assert shot.is_blocked and shot.player3_id == 11
    assert dict(code="reviewed_event_block", event_num=n["miss"], blocker=11) in loaded.diagnostics


@pytest.mark.parametrize("blocked, values, message", [
    (False, {"miss": 2}, "does not fit the recorded event"),
    (False, {"miss": 99}, "does not fit the recorded event"),
    (False, {"make": 11}, "does not fit the recorded event"),
    (False, {"999": 11}, "does not fit the recorded event"),
    (True, {"miss": 12}, "does not fit the recorded event"),
    (False, {"miss": 0}, "Invalid event block override"),
], ids=["shooters_team", "not_on_roster", "made_shot", "unknown_event", "already_blocked", "no_person"])
def test_block_edits_are_validated(blocked, values, message):
    rows, n = missed_and_rebounded(blocked)
    values = {str(n.get(key, key)): value for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_BLOCKS, values))


def tipped_to_opponent():
    """HOME keeps the ball through a held ball, but V3 credits the tip to AWAY."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("jump", 590, HOME, 1, winner_team=AWAY, winner=12, opponent=11),
        e("make", 570, HOME, 2),
    ]))
    return rows, dict(jump=numbered(rows, "Jump Ball"), make=numbered(rows, "Made Shot"))


def test_tip_recipient_edit_names_who_secured_the_jump_ball():
    rows, n = tipped_to_opponent()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, files=edits(EVENT_TIP_RECIPIENTS, {str(n["jump"]): 4}))
    jump = next(x for x in loaded.events if x.event_num == n["jump"])
    # The original reads the recipient as player2 of a jump ball.
    assert (jump.player2_id, jump.team_id) == (4, HOME)
    assert offenses(loaded) == [AWAY, HOME, AWAY]
    assert dict(
        code="reviewed_tip_recipient", event_num=n["jump"], recorded=12, reviewed=4
    ) in loaded.diagnostics
    assert loaded.decoded.raw_rows == rows


def test_tip_recipient_edit_names_a_team_recovery():
    # A tip out of bounds off an AWAY player: HOME recovers it as a team. The
    # original reads such a jump ball's PLAYER3 as the winning team, with no
    # recipient ("when jump ball is tipped out of bounds").
    rows, n = tipped_to_opponent()
    loaded = load(rows, files=edits(EVENT_TIP_RECIPIENTS, {str(n["jump"]): HOME}))
    jump = next(x for x in loaded.events if x.event_num == n["jump"])
    assert jump.team_id == HOME and not hasattr(jump, "player2_id")
    assert offenses(loaded) == [AWAY, HOME, AWAY]
    assert dict(
        code="reviewed_tip_recipient", event_num=n["jump"], recorded=12, reviewed=HOME
    ) in loaded.diagnostics


@pytest.mark.parametrize("values, message", [
    ({"jump": 12}, "does not fit the recorded event"),
    ({"jump": 99}, "does not fit the recorded event"),
    ({"jump": 1610612799}, "does not fit the recorded event"),
    ({"make": 4}, "does not fit the recorded event"),
    ({"999": 4}, "does not fit the recorded event"),
    ({"jump": 0}, "Invalid event tip-recipient override"),
], ids=["recorded_recipient", "not_on_roster", "team_not_in_game", "not_a_jump_ball",
        "unknown_event", "no_person"])
def test_tip_recipient_edits_are_validated(values, message):
    rows, n = tipped_to_opponent()
    values = {str(n.get(key, key)): value for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_TIP_RECIPIENTS, values))


def charge_without_turnover():
    """AWAY's challenge leaves HOME's charge standing, but the feed records no turnover."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, HOME, 1, subtype="Offensive Charge"),
        e("timeout", 590, AWAY, AWAY),
        e("miss", 580, AWAY, 12),
        e("rebound", 578, HOME, 2),
        e("make", 570, HOME, 3),
    ]))
    return rows, dict(
        foul=numbered(rows, "Foul"), timeout=numbered(rows, "Timeout"),
        added=max(r["actionNumber"] for r in rows) + 1,
    )


def test_turnover_edit_adds_the_turnover_v3_omits():
    rows, n = charge_without_turnover()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    entry = dict(before=n["timeout"], player=1, subtype="Offensive Foul Turnover")
    loaded = load(rows, files=edits(EVENT_TURNOVERS, {str(n["added"]): entry}))
    turnover = next(x for x in loaded.events if x.event_num == n["added"])
    assert isinstance(turnover, Turnover) and turnover.event_action_type == 37
    assert (turnover.player1_id, turnover.team_id, turnover.clock) == (1, HOME, "9:50")
    assert turnover.description == "Player1 Offensive Foul Turnover"
    assert offenses(loaded) == [AWAY, HOME, AWAY, HOME, AWAY]
    assert [x.event_num for x in loaded.items[1].events] == [n["foul"], n["added"]]
    assert dict(code="reviewed_added_turnover", event_num=n["added"], **entry) in loaded.diagnostics
    # The added turnover owns no recorded row; every recorded row keeps one event.
    assert turnover.v3_source_indices == ()
    assert turnover.v3_source_row["subType"] == "Offensive Foul Turnover"
    assert sorted(i for x in loaded.events for i in x.v3_source_indices) == list(range(len(rows)))
    assert loaded.decoded.raw_rows == rows


def test_turnover_edit_adds_a_team_turnover():
    # A team's turnover is shaped as the decoder shapes a recorded one: no
    # person, the team as the event's team, the team as V3's person.
    rows, n = charge_without_turnover()
    entry = dict(before=n["timeout"], player=HOME, subtype="Too Many Players Turnover")
    loaded = load(rows, files=edits(EVENT_TURNOVERS, {str(n["added"]): entry}))
    turnover = next(x for x in loaded.events if x.event_num == n["added"])
    assert isinstance(turnover, Turnover) and turnover.event_action_type == 44
    assert (turnover.player1_id, turnover.team_id, turnover.clock) == (0, HOME, "9:50")
    assert turnover.description == "Too Many Players Turnover"
    assert offenses(loaded) == [AWAY, HOME, AWAY, HOME, AWAY]
    assert dict(code="reviewed_added_turnover", event_num=n["added"], **entry) in loaded.diagnostics
    assert (turnover.v3_source_row["personId"], turnover.v3_source_row["teamId"]) == (HOME, 0)
    assert sorted(i for x in loaded.events for i in x.v3_source_indices) == list(range(len(rows)))


@pytest.mark.parametrize("values, message", [
    ({"foul": dict(before="timeout", player=1, subtype="Offensive Foul Turnover")},
     "does not fit the recorded events"),
    ({"added": dict(before="timeout", player=HOME, subtype="Offensive Foul Turnover")},
     "does not fit the recorded events"),
    ({"added": dict(before="timeout", player=1610612799, subtype="Shot Clock Turnover")},
     "does not fit the recorded events"),
    ({"added": dict(before=999, player=1, subtype="Offensive Foul Turnover")},
     "does not fit the recorded events"),
    ({"added": dict(before="timeout", player=99, subtype="Offensive Foul Turnover")},
     "does not fit the recorded events"),
    ({"added": dict(before="timeout", player=1, subtype="Offensive Charge")},
     "does not fit the recorded events"),
    ({"added": dict(before="timeout", player=1, subtype="")}, "Invalid event turnover override"),
    ({"added": dict(before="timeout", player=1)}, "Invalid event turnover override"),
    ({"added": dict(before="added", player=1, subtype="Offensive Foul Turnover")},
     "Invalid event turnover override"),
], ids=["recorded_number", "team_with_player_label", "team_not_in_game", "unknown_event",
        "not_on_roster", "not_a_turnover_label", "no_label", "missing_field", "before_itself"])
def test_turnover_edits_are_validated(values, message):
    rows, n = charge_without_turnover()
    values = {
        str(n.get(key, key)): {
            field: n.get(value, value) if field == "before" else value
            for field, value in entry.items()
        }
        for key, entry in values.items()
    }
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_TURNOVERS, values))


def clock_reset():
    """HOME's shot-clock turnover at 9:30, after which the clock is set back to
    9:45; the feed sorts AWAY's 9:40 basket, played after the reset, by clock."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("miss", 590, HOME, 1),
        e("rebound", 588, HOME, 2),
        e("make", 580, AWAY, 12),
        e("turnover", 570, HOME, 1, subtype="Shot Clock Turnover"),
        e("make", 560, HOME, 3),
    ]))
    turnover = numbered(rows, "Turnover")
    makes = [r["actionNumber"] for r in rows if r["actionType"] == "Made Shot"]
    return rows, dict(rebound=numbered(rows, "Rebound"), turnover=turnover,
                      replayed=makes[1], last=makes[2])


def test_clock_reset_edit_moves_the_replayed_events_after_the_reset():
    rows, n = clock_reset()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    entry = dict(clock="PT09M45.00S", events=[n["replayed"]])
    loaded = load(rows, files=edits(EVENT_CLOCK_RESETS, {str(n["turnover"]): entry}))
    assert offenses(loaded) == [AWAY, HOME, AWAY, HOME, AWAY]
    home, away = loaded.items[1], loaded.items[2]
    assert home.events[-1].event_num == n["turnover"] and home.end_time == "9:30"
    # The possession after the reset starts at the clock the reset set.
    assert [x.event_num for x in away.events] == [n["replayed"]]
    assert (away.start_time, away.end_time) == ("9:45", "9:40")
    assert dict(code="reviewed_clock_reset", event_num=n["turnover"], clock="9:45",
                moved=[n["replayed"]]) in loaded.diagnostics


@pytest.mark.parametrize("values, message", [
    ({"turnover": dict(clock="PT09M45.00S", events=["last"])}, "does not fit the recorded events"),
    ({"turnover": dict(clock="PT09M20.00S", events=["replayed"])}, "does not fit the recorded events"),
    ({"turnover": dict(clock="PT09M35.00S", events=["replayed"])}, "does not fit the recorded events"),
    ({"999": dict(clock="PT09M45.00S", events=["replayed"])}, "does not fit the recorded events"),
    ({"turnover": dict(clock="9:45", events=["replayed"])}, "Invalid event clock-reset override"),
    ({"turnover": dict(clock="PT09M45.00S", events=[])}, "Invalid event clock-reset override"),
], ids=["played_after_the_event", "not_set_back", "replayed_after_the_reset_clock", "unknown_event",
        "not_a_v3_clock", "no_events"])
def test_clock_reset_edits_are_validated(values, message):
    rows, n = clock_reset()
    values = {
        str(n.get(key, key)): dict(entry, events=[n[x] for x in entry["events"]])
        for key, entry in values.items()
    }
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_CLOCK_RESETS, values))


def test_clock_reset_must_end_a_possession():
    # HOME keeps the ball through its offensive rebound, so a reset after the
    # rebound would split HOME's possession at a clock that runs backward.
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("miss", 590, HOME, 1),
        e("miss", 585, HOME, 3),
        e("rebound", 583, HOME, 2),
        e("rebound", 580, HOME, 2),
        e("make", 570, HOME, 4),
    ]))
    miss, rebound, anchor = (r["actionNumber"] for r in rows[3:6])
    entry = dict(clock="PT09M48.00S", events=[miss, rebound])
    with pytest.raises(V3DecodeError, match="must end a possession"):
        load(rows, files=edits(EVENT_CLOCK_RESETS, {str(anchor): entry}))


def test_recorded_clock_reset_follows_the_live_entry_order():
    # 0022301177 Q3 1:14: Memphis' shot-clock violation, after which the table
    # set the clock back to 2:20. The live play-by-play lists actions in the
    # order entered; the reviewed order of the replayed stretch is that order.
    game = "0022301177"
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    with pytest.raises(V3DecodeError, match="additional recorded provider evidence"):
        web.load_game(game, pbp, box, "recorded")
    loader = web.load_game(game, pbp, box, "recorded", overrides=web.reviewed_overrides(game, pbp))
    live = json.loads((DATA / f"live_{game}.json").read_bytes())["game"]["actions"]
    stretch = [458, 461, 462, 463, 464, 468, 469, 470, 471, 681, 473, 475, 476, 477, 478, 480, 481]
    entered = sorted((a for a in live if a["period"] == 3 and a["actionNumber"] in stretch),
                     key=lambda a: a["timeActual"])
    assert [a["actionNumber"] for a in entered] == stretch
    order = [x.event_num for x in loader.events if x.event_num in stretch]
    assert order == stretch
    after = next(p for p in loader.items if p.events[0].event_num == 473)
    assert (after.offense_team_id, after.start_time, after.end_time) == (1610612747, "2:20", "2:06")
    assert loader.counts_by_team == {1610612747: 102, 1610612763: 103}


def stale_substitution():
    """HOME's Player2 leaves for Player6 at 9:50; a stale row at 9:30 takes him
    out again, for Player3, who has been on the floor all along."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("sub", 590, HOME, 2, incoming=6),
        e("make", 580, HOME, 1),
        e("make", 570, AWAY, 12),
        e("sub", 570, HOME, 2, incoming=3),
        e("make", 560, HOME, 6),
    ]))
    first, stale = (r["actionNumber"] for r in rows if r["actionType"] == "Substitution")
    return rows, dict(first=first, stale=stale, make=numbered(rows, "Made Shot"))


def test_removal_edit_drops_a_stale_substitution():
    rows, n = stale_substitution()
    with pytest.raises(V3DecodeError, match="Substitution contradicts"):
        load(rows)
    loaded = load(rows, files=edits(EVENT_REMOVALS, {str(n["stale"]): n["first"]}))
    assert n["stale"] not in [x.event_num for x in loaded.events]
    assert sorted(loaded.events[-2].current_players[HOME]) == [1, 3, 4, 5, 6]
    assert offenses(loaded) == [AWAY, HOME, AWAY, HOME, AWAY]
    assert dict(code="reviewed_removed_event", event_num=n["stale"],
                kept=n["first"]) in loaded.diagnostics
    # The removed row belongs to the substitution kept.
    index = {r["actionNumber"]: i for i, r in enumerate(rows)}
    kept = next(x for x in loaded.events if x.event_num == n["first"])
    assert kept.v3_source_indices == (index[n["first"]], index[n["stale"]])
    assert sorted(i for x in loaded.events for i in x.v3_source_indices) == list(range(len(rows)))


@pytest.mark.parametrize("values, message", [
    ({"stale": "make"}, "removal override does not fit"),
    ({"stale": 999}, "removal override does not fit"),
    ({"stale": "first", "first": "make"}, "removal override does not fit"),
    ({"stale": "stale"}, "Invalid event removal override"),
], ids=["other_kind", "unknown_event", "kept_is_removed", "itself"])
def test_removal_edits_are_validated(values, message):
    rows, n = stale_substitution()
    values = {str(n.get(key, key)): n.get(value, value) for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_REMOVALS, values))


def double_technical_named_nobody():
    """HOME's Player2 and AWAY's Player12 get a double technical whose text names
    nobody, and Player12's half of it is recorded again as a technical of his own."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, HOME, 2, subtype="Double Technical"),
        e("foul", 590, AWAY, 12, subtype="Technical"),
        e("make", 570, HOME, 1),
    ]))
    double = next(r for r in rows if r["subType"] == "Double Technical")
    double["description"] = "Double Technical"
    return rows, dict(double=double["actionNumber"], technical=numbered(rows, "Foul", "Technical"),
                      make=numbered(rows, "Made Shot"))


def test_foul_opponent_and_removal_edits_complete_a_double_technical():
    rows, n = double_technical_named_nobody()
    with pytest.raises(V3DecodeError, match="both recorded participants"):
        load(rows)
    loaded = load(rows, files={
        **edits(EVENT_FOUL_OPPONENTS, {str(n["double"]): 12}),
        **edits(EVENT_REMOVALS, {str(n["technical"]): n["double"]}),
    })
    double = next(x for x in loaded.events if x.event_num == n["double"])
    # The original reads a double foul's second party as player3.
    assert double.is_double_technical and (double.player1_id, double.player3_id) == (2, 12)
    assert n["technical"] not in [x.event_num for x in loaded.events]
    assert dict(code="reviewed_foul_opponent", event_num=n["double"], player_id=12) in loaded.diagnostics
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("values, message", [
    ({"double": 4}, "foul-opponent override does not fit"),
    ({"double": 99}, "foul-opponent override does not fit"),
    ({"double": 12, "technical": 2}, "foul-opponent override does not fit"),
    ({"double": 12, "999": 12}, "foul-opponent override does not fit"),
    ({"double": 0}, "Invalid event foul-opponent override"),
], ids=["same_team", "not_on_roster", "not_a_double_foul", "unknown_event", "no_person"])
def test_foul_opponent_edits_are_validated(values, message):
    rows, n = double_technical_named_nobody()
    values = {str(n.get(key, key)): value for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_FOUL_OPPONENTS, values))


def test_removal_edit_needs_the_kept_event_to_record_the_actor():
    # Player12's technical is not part of a double technical with Player13.
    rows, n = double_technical_named_nobody()
    with pytest.raises(V3DecodeError, match="removal override does not fit"):
        load(rows, files={
            **edits(EVENT_FOUL_OPPONENTS, {str(n["double"]): 13}),
            **edits(EVENT_REMOVALS, {str(n["technical"]): n["double"]}),
        })


def test_foul_opponent_edit_needs_a_double_foul_that_names_nobody():
    rows, n = double_technical_named_nobody()
    next(r for r in rows if r["actionNumber"] == n["double"])["description"] = (
        "Double Technical - Player2, Player12"
    )
    with pytest.raises(V3DecodeError, match="foul-opponent override does not fit"):
        load(rows, files=edits(EVENT_FOUL_OPPONENTS, {str(n["double"]): 12}))


def teamless_excess_timeout_turnover():
    """HOME calls a timeout it does not have: a technical and a turnover, which the
    feed records with neither a team nor a person."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, HOME, HOME, subtype="Excess Timeout Technical"),
        e("turnover", 590, 0, 0, subtype="Excess Timeout Turnover"),
        e("ft", 590, AWAY, 11, category="Technical", attempt=1, total=1, made=True),
        e("make", 570, AWAY, 12),
    ]))
    return rows, dict(turnover=numbered(rows, "Turnover"), make=numbered(rows, "Made Shot"))


def test_team_edit_gives_a_teamless_turnover_its_team():
    rows, n = teamless_excess_timeout_turnover()
    with pytest.raises(V3DecodeError, match="requires a known team"):
        load(rows)
    loaded = load(rows, files=edits(EVENT_TEAMS, {str(n["turnover"]): HOME}))
    turnover = next(x for x in loaded.events if x.event_num == n["turnover"])
    assert (turnover.team_id, turnover.player1_id) == (HOME, 0)
    assert turnover.is_possession_ending_event
    assert offenses(loaded) == [AWAY, HOME, AWAY, HOME]
    assert dict(code="reviewed_event_team", event_num=n["turnover"], team_id=HOME) in loaded.diagnostics
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("values, message", [
    ({"make": AWAY}, "team override does not fit"),
    ({"turnover": 1610612799}, "team override does not fit"),
    ({"turnover": HOME, "999": HOME}, "team override does not fit"),
    ({"turnover": 0}, "Invalid event team override"),
], ids=["recorded_team", "team_not_in_game", "unknown_event", "no_team"])
def test_team_edits_are_validated(values, message):
    rows, n = teamless_excess_timeout_turnover()
    values = {str(n.get(key, key)): value for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_TEAMS, values))


def take_foul_free_throw_recorded_late():
    """AWAY's transition take foul at 9:50 gives HOME one free throw, made by
    Player6 after checking in; the feed records it at HOME's 9:20 and-one."""
    rows = encode_v3(wrap([
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 12, subtype="Transition Take"),
        e("sub", 590, HOME, 2, incoming=6),
        e("make", 580, HOME, 1),
        e("make", 570, AWAY, 11),
        e("make", 560, HOME, 1),
        e("foul", 560, AWAY, 11, subtype="Shooting"),
        e("ft", 560, HOME, 6, attempt=1, total=1, made=True),
        e("ft", 560, HOME, 1, attempt=1, total=1, made=True),
        e("make", 550, AWAY, 13),
    ]))
    late, and_one = (r["actionNumber"] for r in rows if r["actionType"] == "Free Throw")
    return rows, dict(late=late, and_one=and_one, sub=numbered(rows, "Substitution"),
                      take=numbered(rows, "Foul", "Transition Take"))


def test_move_edit_restores_a_free_throw_to_its_foul():
    rows, n = take_foul_free_throw_recorded_late()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows)
    loaded = load(rows, files=edits(EVENT_MOVES, {str(n["late"]): n["sub"]}))
    throw = next(x for x in loaded.events if x.event_num == n["late"])
    assert throw.clock == "9:50" and throw.is_transition_take_foul_ft
    assert not throw.is_possession_ending_event
    trip = next(p for p in loaded.items if throw in p.events)
    assert [x.event_num for x in trip.events][:3] == [n["take"], n["sub"], n["late"]]
    assert offenses(loaded) == [AWAY, HOME, AWAY, HOME, AWAY, HOME]
    assert dict(code="reviewed_moved_event", event_num=n["late"], after=n["sub"],
                recorded="9:20", reviewed="9:50") in loaded.diagnostics


@pytest.mark.parametrize("values, message", [
    ({"late": 999}, "move override does not fit"),
    ({"999": "sub"}, "move override does not fit"),
    ({"late": "late"}, "Invalid event move override"),
], ids=["unknown_anchor", "unknown_event", "itself"])
def test_move_edits_are_validated(values, message):
    rows, n = take_foul_free_throw_recorded_late()
    values = {str(n.get(key, key)): n.get(value, value) for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_MOVES, values))


def test_move_edit_stays_within_one_period():
    rows, n = take_foul_free_throw_recorded_late()
    end = rows[-1]
    end["period"] = 2
    with pytest.raises(V3DecodeError, match="move override does not fit"):
        load(rows, files=edits(EVENT_MOVES, {str(n["late"]): end["actionNumber"]}))


def team_heave(side=""):
    """HOME's period-ending team heave, rebounded by HOME, with the side V3 gives it."""
    case = next(c for c in heave_cases() if c["period"] == 1 and c["start"] == "5"
                and c["rebound"] == "offensive" and not c["blocked"] and not c["substitute"])
    rows = heave_rows(case)
    heave = next(r for r in rows if r["actionType"] == "Heave")
    heave["location"] = side
    return rows, dict(heave=heave["actionNumber"], make=numbered(rows, "Made Shot"))


def test_location_and_block_edits_complete_a_team_heave():
    rows, n = team_heave()
    with pytest.raises(V3DecodeError, match="team evidence"):
        load(rows)
    loaded = load(rows, files={
        **edits(EVENT_LOCATIONS, {str(n["heave"]): "h"}),
        **edits(EVENT_BLOCKS, {str(n["heave"]): 11}),
    })
    heave = next(x for x in loaded.events if x.event_num == n["heave"])
    assert isinstance(heave, V3TeamHeave) and heave.team_id == HOME
    assert heave.is_blocked and heave.player3_id == 11
    recorded = next(d for d in loaded.diagnostics if d["code"] == TEAM_HEAVE_VERSION)
    assert (recorded["location"], recorded["basis"]) == ("h", "reviewed_location")
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("side, values, message", [
    ("h", {"heave": "h"}, "location override does not fit"),
    ("h", {"make": "h"}, "location override does not fit"),
    ("", {"heave": "x"}, "Invalid event location override"),
], ids=["recorded_side", "not_a_heave", "not_a_side"])
def test_location_edits_are_validated(side, values, message):
    rows, n = team_heave(side)
    values = {str(n[key]): value for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_LOCATIONS, values))


def recorded_jump_ball_game(renumber=True):
    """0022500001 Q3 6:50: V3 leaves jump ball 424 undecided; live records it.

    The live-number edit is read by the decoder, so the decoder is checked
    here; the recorded 0022500974 test below runs it through a whole game.
    """
    pbp, box, live = (
        (DATA / name).read_bytes()
        for name in ("stats_v3_0022500001.json", "stats_v3_boxscore_0022500001.json",
                     "live_0022500001.json")
    )
    if renumber:
        payload = json.loads(live)
        next(a for a in payload["game"]["actions"] if a["actionNumber"] == 424)["actionNumber"] = 9424
        live = json.dumps(payload).encode()
    context = web.context_from_boxscore(GAME, pbp, box, "recorded")
    return pbp, context, V3JumpBallEvidence(live, "recorded", context.pbp_sha256)


def test_live_number_edit_matches_a_renumbered_jump_ball():
    pbp, context, renumbered = recorded_jump_ball_game()
    with pytest.raises(V3DecodeError, match="lacks this jump ball"):
        DecodedV3(pbp, context, renumbered)
    decoded = DecodedV3(pbp, context, renumbered, live_numbers={424: 9424})
    expected = DecodedV3(*recorded_jump_ball_game(renumber=False))
    assert decoded.projected == expected.projected
    jump, = decoded.recorded_jump_balls
    assert jump == dict(expected.recorded_jump_balls[0], live_action_number=9424,
                        basis="reviewed live action number, period and V3 jumper personId")
    assert decoded.raw_rows == expected.raw_rows


@pytest.mark.parametrize("renumber, values", [
    (False, {424: 9424}),
    (False, {2: 9424}),
], ids=["live_keeps_the_number", "not_a_jump_ball"])
def test_live_number_edits_are_validated(renumber, values):
    pbp, context, evidence = recorded_jump_ball_game(renumber)
    with pytest.raises(V3DecodeError, match="live-number override does not fit"):
        DecodedV3(pbp, context, evidence, live_numbers=values)


@pytest.mark.parametrize("values", [{"424": 424}, {"424": "x"}], ids=["itself", "not_a_number"])
def test_live_number_entries_name_another_action(values):
    pbp = (DATA / "stats_v3_0022500001.json").read_bytes()
    overrides = V3Overrides(edits(EVENT_LIVE_NUMBERS, values), "Controlled review",
                            hashlib.sha256(pbp).hexdigest())
    with pytest.raises(V3DecodeError, match="Invalid event live-number override"):
        overrides.decode(pbp)


def test_reviewed_corrections_file_is_well_formed():
    assert web.REVIEWED_CORRECTIONS, "the corrections file is empty"
    for game_id, entry in web.REVIEWED_CORRECTIONS.items():
        assert re.fullmatch(r"(00|10)\d{8}", game_id)
        assert set(entry) == {"pbp_sha256", "source", "files"}
        assert re.fullmatch(r"[0-9a-f]{64}", entry["pbp_sha256"])
        assert entry["source"].strip() and set(entry["files"]) <= SUPPORTED


def test_every_reviewed_correction_has_its_recording():
    for game_id, entry in web.REVIEWED_CORRECTIONS.items():
        folder = DATA if game_id.startswith("00") else ROOT / "tests/parity/data/wnba"
        pbp = (folder / f"stats_v3_{game_id}.json").read_bytes()
        assert hashlib.sha256(pbp).hexdigest() == entry["pbp_sha256"], game_id


def test_recorded_correction_moves_curry_technical_free_throw():
    pbp = (DATA / "stats_v3_0022500169.json").read_bytes()
    box = (DATA / "stats_v3_boxscore_0022500169.json").read_bytes()
    live = (DATA / "live_0022500169.json").read_bytes()
    warriors, suns = 1610612744, 1610612756
    fetch = lambda url: web.SavedResponse(live, url)  # noqa: E731
    # Q4 2:48: V3 lists Curry's technical free throw (648) after his second free
    # throw (647); on video the technical came first. As recorded, the original
    # credits the Warriors with Phoenix's 2:27-2:07 trip and raises.
    with pytest.raises(TeamHasBackToBackPossessionsException):
        web.load_game("0022500169", pbp, box, "recorded", fetch_live=fetch)
    overrides = web.reviewed_overrides("0022500169", pbp)
    loader = web.load_game("0022500169", pbp, box, "recorded", overrides=overrides,
                           fetch_live=fetch)
    trip = next(p for p in loader.items if any(x.event_num == 647 for x in p.events))
    index = loader.items.index(trip)
    assert [x.event_num for x in trip.events] == [643, 645, 646, 648, 647]
    assert trip.offense_team_id == warriors and trip.end_time == "2:48"
    suns_trip, after = loader.items[index + 1], loader.items[index + 2]
    assert suns_trip.offense_team_id == suns
    assert (suns_trip.start_time, suns_trip.end_time) == ("2:48", "2:07")
    assert after.offense_team_id == warriors and after.start_time == "2:07"
    assert dict(code="reviewed_event_order", moves=[[648, 647]]) in loader.diagnostics
    assert loader.counts_by_team == {suns: 100, warriors: 98}
    with pytest.raises(V3DecodeError, match="covers different play-by-play bytes"):
        web.reviewed_overrides("0022500169", pbp + b" ")


@pytest.mark.parametrize("game, trip, code", [
    ("0022500775", [448, 450, 459, 451, 462], "reviewed_event_order"),
    ("0022500054", [190, 192, 262], "reviewed_event_subtype"),
    ("0022501009", [158, 182, 674], "reviewed_event_subtype"),
    ("0022500944", [391, 393, 394, 396], "reviewed_event_subtype"),
    ("0022501070", [500, 503, 504, 505], "reviewed_event_subtype"),
    ("0022501079", [684, 686, 687, 688], "reviewed_event_subtype"),
    ("0022500684", [151, 152, 154, 155], "reviewed_event_clock"),
])
def test_recorded_corrections_from_video_review(game, trip, code):
    # 0022500775 Q3 6:58: Ball's technical free throw came first. 0022500054 Q2
    # 11:06 and 0022501009 Q1 0:47: the made free throw was 1 of 2, and a
    # violation on the second ended the trip. 0022500944 Q3 9:38: a lane
    # violation turnover. 0022501070 Q3 2:27: replay made the foul a personal
    # foul. 0022501079 Q4 8:09: Miller's lane violation gave Memphis the ball.
    # 0022500684 Q1 0:19.4: Hardaway Jr.'s and-one.
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        web.load_game(game, pbp, box, "recorded")
    loader = web.load_game(game, pbp, box, "recorded",
                           overrides=web.reviewed_overrides(game, pbp))
    possession = next(p for p in loader.items if any(x.event_num == trip[-1] for x in p.events))
    assert [x.event_num for x in possession.events][-len(trip):] == trip
    following = loader.items[loader.items.index(possession) + 1]
    assert following.offense_team_id != possession.offense_team_id
    assert following.start_time == possession.end_time
    assert any(d["code"] == code for d in loader.diagnostics)


@pytest.mark.parametrize("game, recorded, trip, offense, check, counts", [
    ("0022500119", "team evidence", [674, 676, 677], 1610612742,
     (674, "player3_id", 1631096), {1610612760: 97, 1610612742: 98}),
    ("0022500233", "additional recorded provider evidence", [697, 698, 699], 1610612746,
     (698, "is_real_rebound", False), {1610612746: 93, 1610612738: 94}),
    ("0022500421", "additional recorded provider evidence", [506, 782, 784, 508, 510, 511],
     1610612758, (784, "oreb", True), {1610612758: 98, 1610612765: 98}),
    ("0022500449", "additional recorded provider evidence",
     [571, 572, 573, 575, 617, 578, 579, 580], 1610612751,
     (580, "oreb", False), {1610612751: 96, 1610612744: 95}),
    ("0022500974", "lacks this jump ball", [811, 812, 804, 807, 751], 1610612747,
     (804, "team_id", 1610612747), {1610612743: 108, 1610612747: 109}),
])
def test_recorded_corrections_for_other_rejections(game, recorded, trip, offense, check, counts):
    # 0022500119 Q4 0:00.3: Holmgren blocked Flagg's heave for Dallas, logged
    # without a side or the block. 0022500233 Q4 0:00, 0022500421 Q3 1:50: a
    # rebound listed before its miss. 0022500449 Q4 9:30: a lane violation on
    # the second free throw, which was shot again. 0022500974 OT 2:49: a lodged
    # ball's team rebound logged twice, and a renumbered jump ball.
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    live = DATA / f"live_{game}.json"
    fetch = (lambda url: web.SavedResponse(live.read_bytes(), url)) if live.exists() else None
    with pytest.raises(V3DecodeError, match=recorded):
        web.load_game(game, pbp, box, "recorded", fetch_live=fetch)
    loader = web.load_game(game, pbp, box, "recorded",
                           overrides=web.reviewed_overrides(game, pbp), fetch_live=fetch)
    possession = next(p for p in loader.items if any(x.event_num == trip[0] for x in p.events))
    assert [x.event_num for x in possession.events] == trip
    assert possession.offense_team_id == offense
    event, attribute, value = check
    assert getattr(next(x for x in loader.events if x.event_num == event), attribute) == value
    assert loader.counts_by_team == counts
    rows = json.loads(pbp)["game"]["actions"]
    assert sorted(i for x in loader.events for i in x.v3_source_indices) == list(range(len(rows)))


@pytest.mark.parametrize("game, recorded, trip, offense, counts", [
    ("0022400013", TeamHasBackToBackPossessionsException, [262, 267, 268], 1610612741,
     {1610612739: 108, 1610612741: 107}),
    ("0022400116", TeamHasBackToBackPossessionsException, [65, 68, 69], 1610612744,
     {1610612744: 96, 1610612740: 96}),
    ("0022400313", TeamHasBackToBackPossessionsException, [530, 531, 532, 534, 535, 537],
     1610612758, {1610612759: 99, 1610612758: 98}),
    ("0022400326", V3DecodeError, [461, 466, 711, 712, 585, 473, 474, 475, 476], 1610612742,
     {1610612742: 102, 1610612764: 104}),
    ("0022400345", TeamHasBackToBackPossessionsException,
     [726, 727, 729, 735, 734, 736, 738, 741, 742], 1610612763,
     {1610612763: 108, 1610612738: 108}),
    ("0022400512", TeamHasBackToBackPossessionsException, [588, 634, 658], 1610612764,
     {1610612764: 90, 1610612755: 90}),
    ("0022400625", TeamHasBackToBackPossessionsException, [615, 617, 618, 619], 1610612742,
     {1610612742: 99, 1610612760: 100}),
    ("0022400739", TeamHasBackToBackPossessionsException, [492, 499, 500, 501, 502, 503],
     1610612760, {1610612761: 95, 1610612760: 95}),
    ("0022400758", TeamHasBackToBackPossessionsException,
     [177, 178, 185, 490, 188, 189, 191, 192, 193, 194, 198, 199, 201, 202], 1610612766,
     {1610612766: 91, 1610612751: 92}),
    ("0022400834", TeamHasBackToBackPossessionsException, [359, 364, 365], 1610612766,
     {1610612766: 101, 1610612744: 100}),
    ("0022400862", TeamHasBackToBackPossessionsException,
     [300, 302, 303, 304, 324, 307, 308, 309], 1610612745,
     {1610612745: 95, 1610612758: 95}),
])
def test_recorded_corrections_from_2024_25_video_review(game, recorded, trip, offense, counts):
    # 0022400013 Q2 5:51, 0022400834 Q3 11:17: a block caused a held ball, listed
    # in the league's order: miss, the jump-ball winner's team rebound, jump ball.
    # 0022400116 Q1 6:40, 0022400739 Q3 1:54: the jump ball's tip recipient.
    # 0022400313 Q4 11:25: an offensive foul turnover. 0022400326 Q3 3:07: the
    # technical free throw between two free throws. 0022400512 Q4 3:21: a free
    # throw 1 of 2. 0022400625 Q4 9:43: a transition take foul. 0022400345 Q4
    # 0:19.1, 0022400758 Q1 3:39, 0022400862 Q2 1:06: a successful challenge.
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    live = DATA / f"live_{game}.json"
    fetch = (lambda url: web.SavedResponse(live.read_bytes(), url)) if live.exists() else None
    # 0022400116's box score lists Brandon Boston without the "Jr." its rows use.
    aliases = {1630527: ["Boston Jr."]} if game == "0022400116" else None
    with pytest.raises(recorded):
        web.load_game(game, pbp, box, "recorded", aliases=aliases, fetch_live=fetch)
    loader = web.load_game(game, pbp, box, "recorded", aliases=aliases,
                           overrides=web.reviewed_overrides(game, pbp), fetch_live=fetch)
    possession = next(p for p in loader.items if any(x.event_num == trip[0] for x in p.events))
    assert [x.event_num for x in possession.events] == trip
    assert possession.offense_team_id == offense
    assert loader.counts_by_team == counts
    rows = json.loads(pbp)["game"]["actions"]
    assert sorted(i for x in loader.events for i in x.v3_source_indices) == list(range(len(rows)))


@pytest.mark.parametrize("game, recorded, trip, offense, counts", [
    ("0022300470", TeamHasBackToBackPossessionsException, [647, 649, 650, 652, 653],
     1610612763, {1610612763: 100, 1610612761: 101}),
    ("0022300512", InvalidNumberOfStartersException, [359, 345, 361, 360], 1610612765,
     {1610612758: 103, 1610612765: 102}),
    ("0022300866", TeamHasBackToBackPossessionsException, [431, 432, 433, 435, 437, 439],
     1610612751, {1610612751: 93, 1610612737: 93}),
    ("0022300019", TeamHasBackToBackPossessionsException, [577, 580, 582, 590, 586, 587],
     1610612755, {1610612755: 107, 1610612754: 107}),
    ("0022300910", TeamHasBackToBackPossessionsException, [524, 528, 529], 1610612764,
     {1610612766: 98, 1610612764: 99}),
    ("0022301024", TeamHasBackToBackPossessionsException, [410, 411, 412], 1610612762,
     {1610612762: 99, 1610612745: 99}),
    ("0022300609", TeamHasBackToBackPossessionsException, [442, 443, 446, 450, 447, 452, 454],
     1610612763, {1610612763: 95, 1610612761: 93}),
    ("0022300322", TeamHasBackToBackPossessionsException, [152, 207], 1610612743,
     {1610612743: 102, 1610612751: 102}),
    ("0022300933", TeamHasBackToBackPossessionsException, [586, 590, 592, 595, 597],
     1610612766, {1610612766: 98, 1610612765: 98}),
    ("0022300173", TeamHasBackToBackPossessionsException, [390, 411, 394], 1610612753,
     {1610612749: 100, 1610612753: 99}),
    ("0022300977", TeamHasBackToBackPossessionsException, [455, 458], 1610612765,
     {1610612748: 94, 1610612765: 93}),
    ("0022300474", V3DecodeError, [377, 385], 1610612765, {1610612765: 110, 1610612762: 109}),
])
def test_recorded_corrections_from_2023_24_review(game, recorded, trip, offense, counts):
    # 0022300470 Q4 0:48.1: Smart's lane violation on his second free throw gave
    # Toronto the ball, so its team rebound is real. 0022300512 Q3: Burks'
    # flopping technical at the start came from the bench; the period-start box
    # score the original then reads lists six Kings, so the starters are reviewed.
    # 0022300866 Q3 4:03: Johnson's and-one, its made 3 recorded a second early.
    # 0022300019 Q4 10:40: the free throws recorded as Maxey's makes were missed,
    # and Philadelphia kept the ball. 0022300910 Q4 9:34 and 0022301024 Q3 5:43: a
    # successful challenge's turnover, which V3 does not record, is added.
    # 0022300609 Q3 1:42: the jump ball went out of bounds off Boucher, a Memphis
    # team recovery. 0022300322 Q1 0:41.8 and 0022300933 Q4 3:45: fouls typed away
    # from play were a personal and a loose ball foul. 0022300173 Q3 11:08: a lane
    # violation voided only the first free throw. 0022300977 Q4 11:24: Adebayo's
    # steal at a jump ball, listed before the jump ball violation that follows it.
    # 0022300474 Q3 8:45: a technical after a held ball's whistle, recorded at the
    # shot's clock, two seconds earlier, between the miss and its team rebound.
    check_recorded_correction(game, recorded, trip, offense, counts)


def check_recorded_correction(game, recorded, trip, offense, counts):
    """The recording fails as recorded and parses with its reviewed correction."""
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    live = DATA / f"live_{game}.json"
    fetch_live = (lambda url: web.SavedResponse(live.read_bytes(), url)) if live.exists() else None

    def fetch(period, url, params):
        path = DATA / f"stats_boxscoretraditionalv2_{game}_period_{period}.json"
        return SimpleNamespace(content=path.read_bytes(), url=url, status_code=200, reason="OK")

    with pytest.raises(recorded):
        web.load_game(game, pbp, box, "recorded", fetch_boxscore=fetch, fetch_live=fetch_live)
    loader = web.load_game(game, pbp, box, "recorded", fetch_boxscore=fetch, fetch_live=fetch_live,
                           overrides=web.reviewed_overrides(game, pbp))
    possession = next(p for p in loader.items if any(x.event_num == trip[0] for x in p.events))
    assert [x.event_num for x in possession.events] == trip
    assert possession.offense_team_id == offense
    following = loader.items[loader.items.index(possession) + 1]
    assert following.offense_team_id != offense
    assert loader.counts_by_team == counts
    rows = json.loads(pbp)["game"]["actions"]
    assert sorted(i for x in loader.events for i in x.v3_source_indices) == list(range(len(rows)))
    return loader


@pytest.mark.parametrize("game, recorded, trip, offense, counts, checks", [
    ("0022200055", V3DecodeError, [451, 459, 458, 455, 457, 460, 461, 464, 465, 466], 1610612756,
     {1610612756: 103, 1610612744: 102},
     [(458, "player3_id", 202691), (458, "v3_source_indices", (329, 330))]),
    ("0022200234", V3DecodeError, [225, 227, 723, 230], 1610612747,
     {1610612747: 104, 1610612765: 103}, [(723, "v3_source_indices", (161, 174))]),
    ("0022200323", V3DecodeError, [718, 719, 720, 723, 724], 1610612754,
     {1610612754: 112, 1610612758: 113}, [(724, "team_id", 1610612754)]),
    ("0022200325", TeamHasBackToBackPossessionsException, [396, 398, 399, 404, 402], 1610612742,
     {1610612742: 105, 1610612765: 107},
     [(404, "clock", "6:41"), (404, "is_transition_take_foul_ft", True)]),
    ("0022200363", TeamHasBackToBackPossessionsException, [624, 627, 626, 629], 1610612753,
     {1610612746: 103, 1610612753: 103}, [(629, "is_lane_violation", True)]),
    ("0022200473", TeamHasBackToBackPossessionsException, [150, 152, 153, 158], 1610612742,
     {1610612750: 91, 1610612742: 91}, [(158, "is_possession_ending_event", True)]),
    ("0022200591", TeamHasBackToBackPossessionsException, [64, 83, 66], 1610612759,
     {1610612759: 105, 1610612738: 104}, [(83, "is_possession_ending_event", False)]),
    ("0022200914", TeamHasBackToBackPossessionsException, [456, 457, 459, 460, 463], 1610612739,
     {1610612739: 97, 1610612761: 97},
     [(459, "is_real_rebound", False), (463, "is_possession_ending_event", True)]),
    ("0022200996", TeamHasBackToBackPossessionsException, [541, 540, 542, 543, 544], 1610612763,
     {1610612763: 101, 1610612744: 102}, []),
    ("0022201006", TeamHasBackToBackPossessionsException, [179, 180, 181, 182], 1610612765,
     {1610612754: 104, 1610612765: 105}, []),
    ("0022201115", TeamHasBackToBackPossessionsException,
     [317, 318, 319, 322, 323, 327, 328, 329, 333, 335, 336, 337], 1610612763,
     {1610612763: 100, 1610612737: 100}, [(326, "is_possession_ending_event", True)]),
])
def test_recorded_corrections_from_2022_23_review(game, recorded, trip, offense, counts, checks):
    # 0022200055 Q3 6:31: Booker and Thompson's double technical, which names
    # nobody, with Thompson's half recorded again as his own technical (481).
    # 0022200234 Q2 7:08: a stale Nunn-for-Schroder substitution (248), left by
    # the scorer's later one at 8:51 (723). 0022200323 Q4 1:24: Indiana's excess
    # timeout turnover, recorded without a team. 0022200325 Q3 6:41: Bullock's
    # free throw for the transition take foul, recorded at the 6:03 and-one.
    # 0022200363 Q4 2:15: Wagner's lane violation, recorded without a subtype.
    # 0022200473 Q1 0:11.9: Reid's foul, listed after the free throws it caused.
    # 0022200591 Q1 7:42: Jones's away-from-play free throw, at a clock with
    # Sochan's free throws. 0022200914 Q4 11:39: a fake Raptors team rebound
    # before the jump ball Cleveland won, and LeVert's loose ball foul.
    # 0022200996 Q4 and 0022201006 Q2: a replay and a violation listed before
    # the period's start. 0022201115 Q2 0:06: Jackson Jr.'s block and Morant's
    # rebound, listed after the whistles and the challenge that followed them.
    loader = check_recorded_correction(game, recorded, trip, offense, counts)
    for event, attribute, value in checks:
        assert getattr(next(x for x in loader.events if x.event_num == event), attribute) == value
    removed = web.REVIEWED_CORRECTIONS[game]["files"].get(EVENT_REMOVALS, {})
    assert not {int(n) for n in removed} & {x.event_num for x in loader.events}


@pytest.mark.parametrize("game, recorded, trip, offense, counts, checks", [
    ("0022100039", V3DecodeError, [665, 666, 655, 656, 659], 1610612758,
     {1610612758: 99, 1610612744: 100}, [(666, "clock", "0:59.2")]),
    ("0022100107", TeamHasBackToBackPossessionsException, [631, 632], 1610612747,
     {1610612745: 106, 1610612747: 107}, [(632, "player1_id", 0), (632, "team_id", 1610612747)]),
    ("0022100115", TeamHasBackToBackPossessionsException, [291, 341, 342, 293, 294], 1610612750,
     {1610612746: 100, 1610612750: 99}, []),
    ("0022100142", TeamHasBackToBackPossessionsException, [286, 291], 1610612749,
     {1610612749: 99, 1610612764: 97}, [(291, "event_action_type", 44)]),
    ("0022100172", TeamHasBackToBackPossessionsException,
     [636, 637, 638, 640, 641, 642, 643, 644, 645, 660], 1610612762,
     {1610612754: 98, 1610612762: 97}, [(660, "is_possession_ending_event", True)]),
    ("0022100179", V3DecodeError, [639, 640, 642, 644, 645, 646, 647, 648, 650], 1610612740,
     {1610612740: 95, 1610612751: 97}, [(650, "is_possession_ending_event", True)]),
    ("0022100202", TeamHasBackToBackPossessionsException,
     [610, 612, 613, 618, 619, 616, 614, 622], 1610612737,
     {1610612753: 100, 1610612737: 100}, [(618, "is_possession_ending_event", False)]),
    ("0022100267", TeamHasBackToBackPossessionsException, [486, 487, 488, 490], 1610612739,
     {1610612739: 102, 1610612756: 101}, []),
    ("0022100452", TeamHasBackToBackPossessionsException, [346, 348, 349], 1610612739,
     {1610612739: 100, 1610612737: 99}, [(349, "is_lane_violation", True)]),
    ("0022100596", V3DecodeError, [81, 82, 86, 85], 1610612748,
     {1610612756: 98, 1610612748: 97}, [(82, "clock", "4:28")]),
    ("0022100718", TeamHasBackToBackPossessionsException, [185, 248], 1610612751,
     {1610612747: 94, 1610612751: 94}, [(248, "is_possession_ending_event", True)]),
    ("0022100762", TeamHasBackToBackPossessionsException, [148, 149, 151], 1610612748,
     {1610612738: 97, 1610612748: 96}, [(151, "is_no_turnover", False)]),
    ("0022100819", TeamHasBackToBackPossessionsException, [297, 305, 300, 301, 303, 304],
     1610612740, {1610612745: 99, 1610612740: 99}, [(304, "is_lane_violation", True)]),
    ("0022100830", TeamHasBackToBackPossessionsException, [682, 683, 685], 1610612750,
     {1610612750: 103, 1610612758: 103}, [(685, "is_no_turnover", False)]),
    ("0022100865", TeamHasBackToBackPossessionsException,
     [176, 177, 178, 179, 181, 182, 183, 184], 1610612745,
     {1610612745: 95, 1610612762: 95}, [(176, "clock", "0:00.6")]),
    ("0022100968", TeamHasBackToBackPossessionsException,
     [624, 625, 626, 627, 628, 634, 636, 641], 1610612765,
     {1610612737: 100, 1610612765: 99}, [(641, "is_possession_ending_event", True)]),
    ("0022101030", V3DecodeError, [164, 165, 149, 150, 184, 185, 153, 156, 157, 158, 159],
     1610612753, {1610612751: 104, 1610612753: 106}, [(165, "clock", "1:11")]),
    ("0022101135", V3DecodeError, [643, 644], 1610612762,
     {1610612762: 94, 1610612746: 93}, [(644, "team_id", 1610612762)]),
])
def test_recorded_corrections_from_2021_22_review(game, recorded, trip, offense, counts, checks):
    # 0022100039 Q4 0:59.2 and 0022101030 Q1 1:11: a miss and its team rebound,
    # added after the game, with the rebound listed after the challenge and jump
    # ball that followed it. 0022100107 Q4 2:31: Bazemore's free throws, voided
    # after the fact, left nothing to end the Lakers' possession; a Lakers team
    # turnover does. 0022100142 Q2 2:44: Hill's basket, taken back for too many
    # players, left nothing to end Milwaukee's; a Bucks too many players team
    # turnover does. 0022100865 Q1 0:00.6: Schroder's miss and the Rockets
    # rebound, played before the review that put 0.6 seconds back, recorded at
    # 0:00. 0022100115 Q3 and 0022100267 Q4: delay of game
    # violations listed before the period's start. 0022100172 Q4 1:54:
    # Whiteside's second free throw and the Pacers rebound, listed after the
    # jump ball that followed them. 0022100179 Q4 0:01.8: a delay of game
    # violation between Valanciunas' blocked dunk and Durant's rebound.
    # 0022100202 Q4 4:07: substitutions between Bogdanovic's made free throw and
    # Bamba's loose ball foul. 0022100452 Q3 9:50 and 0022100819 Q2 1:38: lane
    # violations recorded without a subtype. 0022100596 Q1 4:28: Yurtseven's
    # rebound, listed after the review and Strus' turnover that followed it.
    # 0022100718 Q2 10:14: a jump ball violation between the jump ball the
    # Lakers won and Edwards' held ball turnover. 0022100762 Q2 11:40 and
    # 0022100830 Q4 0:36.4: offensive loose ball foul turnovers recorded
    # without a subtype. 0022100968 Q4 0:01.6: Bogdanovic's foul, listed after
    # the free throws it caused. 0022101135 Q4 0:10: Utah's excess timeout
    # turnover, recorded without a team.
    loader = check_recorded_correction(game, recorded, trip, offense, counts)
    for event, attribute, value in checks:
        assert getattr(next(x for x in loader.events if x.event_num == event), attribute) == value


def test_recorded_clock_from_2021_22_review():
    # 0022100756 Q4 1:44: Reed's airball, which Nnaji caught as the shot clock
    # expired. His rebound is recorded at 1:42, after the 1:43 turnover that
    # ends the possession, so the possession's clock runs backward.
    game = "0022100756"
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()

    def trip(loader):
        possession = next(p for p in loader.items if any(x.event_num == 582 for x in p.events))
        return [(x.event_num, x.seconds_remaining) for x in possession.events]

    assert trip(web.load_game(game, pbp, box, "recorded")) == [(581, 104), (582, 102), (583, 103)]
    loader = web.load_game(game, pbp, box, "recorded", overrides=web.reviewed_overrides(game, pbp))
    assert trip(loader) == [(581, 104), (582, 103), (583, 103)]
    assert loader.counts_by_team == {1610612749: 97, 1610612743: 95}
