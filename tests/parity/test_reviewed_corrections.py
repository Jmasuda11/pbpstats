"""Reviewed corrections: the original's override files plus play-by-play edits, bound to exact bytes."""

import hashlib
import json
import re

import pytest

from pbpstats.data_loader.stats_nba.possessions.loader import (
    TeamHasBackToBackPossessionsException,
)
from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3Context,
    V3DecodeError,
    V3Overrides,
    web,
)
from pbpstats.data_loader.stats_nba_v3.overrides import (
    EVENT_CLOCKS,
    EVENT_ORDER,
    EVENT_SUBTYPES,
    SUPPORTED,
)
from pbpstats.resources.enhanced_pbp import Turnover
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, e, encode_v3, wrap

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
    ({"foul": "PT00M20.40S"}, "moves an event to another second"),
    ({"foul": "PT00M19.80S"}, "breaks the recorded order"),
    ({"999": "PT00M19.40S"}, "names an event not in the source"),
    ({"foul": "0:19.4"}, "Invalid event clock override"),
], ids=["another_second", "breaks_order", "unknown_event", "not_a_v3_clock"])
def test_clock_edits_are_validated(values, message):
    rows, foul, ft = and_one_a_tenth_later()
    values = {str(foul) if key == "foul" else key: value for key, value in values.items()}
    with pytest.raises(V3DecodeError, match=message):
        load(rows, files=edits(EVENT_CLOCKS, values))


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
