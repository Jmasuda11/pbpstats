import json
import socket
from collections import Counter
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.context import V3GameContext
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData

DATA = Path(__file__).resolve().parents[1] / "data"
GAME = "0021900001"
HOME, AWAY = 1610612761, 1610612740


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("classification attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def row(kind="Made Shot", subtype="Jump Shot", **changes):
    data = dict(
        actionId=1,
        actionNumber=1,
        period=1,
        clock="PT11M00S",
        actionType=kind,
        subType=subtype,
        description="Smith Jump Shot (2 PTS)",
        personId=1,
        teamId=HOME,
        location="h",
        shotValue=0,
        shotResult="",
        isFieldGoal=0,
    )
    if kind in ("Made Shot", "Missed Shot"):
        data.update(
            shotValue=2,
            shotResult="Made" if kind == "Made Shot" else "Missed",
            isFieldGoal=1,
        )
    data.update(changes)
    return data


def load(rows, complete=False):
    raw = StatsNbaV3PbpLoader(
        GAME,
        SimpleNamespace(
            load_data=lambda _: V3PbpSourceData(
                {"game": {"gameId": GAME, "actions": rows}}
            )
        ),
    )
    facts = StatsNbaV3ParticipantLoader(
        raw, V3GameContext(GAME, HOME, AWAY), snapshot_complete=complete
    )
    return StatsNbaV3EventLoader(facts)


@pytest.mark.parametrize(
    "game,home,away,count,score",
    [
        (GAME, HOME, AWAY, 573, (130, 122)),
        ("0022400001", 1610612738, 1610612737, 445, (116, 117)),
    ],
)
def test_recorded_games_classify_every_row_and_reconcile_scoring(
    game, home, away, count, score
):
    raw = StatsNbaV3PbpLoader(game, StatsNbaV3PbpFileLoader(DATA))
    before = raw.source_data
    facts = StatsNbaV3ParticipantLoader(
        raw, V3GameContext(game, home, away), snapshot_complete=True
    )
    result = StatsNbaV3EventLoader(facts)
    assert len(result.items) == count
    assert [e.participants for e in result.items] == list(facts.items)
    assert sorted(i for e in result.items for i in e.group.source_indices) == list(
        range(len(raw.items))
    )
    totals = Counter()
    for event in result.items:
        totals[event.team_id] += event.recorded_points
        source = event.group.primary
        if source.get("scoreHome") not in (None, ""):
            assert totals[home] == int(source.get("scoreHome"))
            assert totals[away] == int(source.get("scoreAway"))
        if event.kind == "rebound":
            assert event.rebound_type is None
    assert (totals[home], totals[away]) == score
    assert any(
        p.status == "unresolved"
        for e in result.items
        for p in e.participants.participants.values()
    )
    assert raw.source_data == before


def test_paired_v2_confirms_event_families_not_a_numeric_projection():
    raw = StatsNbaV3PbpLoader(GAME, StatsNbaV3PbpFileLoader(DATA))
    events = StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(raw, V3GameContext(GAME, HOME, AWAY))
    ).items
    table = json.loads((DATA / f"pbp/stats_{GAME}.json").read_bytes())["resultSets"][0]
    legacy = {
        r["EVENTNUM"]: r
        for r in (dict(zip(table["headers"], values)) for values in table["rowSet"])
    }
    kinds = {
        1: "field_goal",
        2: "field_goal",
        3: "free_throw",
        4: "rebound",
        5: "turnover",
        6: "foul",
        7: "violation",
        8: "substitution",
        9: "timeout",
        10: "jump_ball",
        12: "period_start",
        13: "period_end",
        18: "replay",
    }
    for event in events:
        old = legacy[event.group.primary.action_number]
        assert event.kind == kinds[old["EVENTMSGTYPE"]]
        if event.kind == "field_goal":
            assert event.is_made == (old["EVENTMSGTYPE"] == 1)


@pytest.mark.parametrize(
    "subtype,category,attempt,total,restart",
    [
        ("Free Throw 1 of 1", "regular", 1, 1, "context_required"),
        ("Free Throw 1 of 2", "regular", 1, 2, "context_required"),
        ("Free Throw 2 of 2", "regular", 2, 2, "context_required"),
        ("Free Throw 1 of 3", "regular", 1, 3, "context_required"),
        ("Free Throw 2 of 3", "regular", 2, 3, "context_required"),
        ("Free Throw 3 of 3", "regular", 3, 3, "context_required"),
        ("Free Throw Technical", "technical", 1, 1, "resume_interrupted_play"),
        ("Free Throw Clear Path 2 of 2", "clear_path", 2, 2, "shooting_team_retains"),
        ("Free Throw Flagrant 2 of 2", "flagrant", 2, 2, "shooting_team_retains"),
    ],
)
@pytest.mark.parametrize("miss", [False, True])
def test_free_throw_outcome_trip_position_and_restart_are_separate(
    subtype, category, attempt, total, restart, miss
):
    description = (
        ("MISS " if miss else "") + "Smith " + subtype + ("" if miss else " (1 PTS)")
    )
    event = load([row("Free Throw", subtype, description=description)]).items[0]
    assert event.is_made is not miss
    assert event.recorded_points == (0 if miss else 1)
    assert event.free_throw.category == category
    assert (event.free_throw.attempt, event.free_throw.total) == (attempt, total)
    assert event.free_throw.is_last_attempt == (attempt == total)
    assert event.free_throw.restart == restart
    assert not hasattr(event, "is_possession_ending_event")


@pytest.mark.parametrize(
    "fields,match",
    [
        ({"shotResult": "Missed"}, "shotResult"),
        ({"shotValue": True}, "shotValue"),
        ({"shotValue": 2.0}, "shotValue"),
        ({"shotValue": 4}, "shotValue"),
        ({"isFieldGoal": True}, "isFieldGoal"),
        ({"isFieldGoal": 0}, "isFieldGoal"),
        ({"description": "MISS Smith Jump Shot"}, "conflicts"),
        ({"description": "Smith 3PT Jump Shot (3 PTS)"}, "conflicts"),
        ({"personId": 0}, "actor is unresolved"),
        ({"teamId": 0, "location": ""}, "requires a team"),
    ],
)
def test_conflicting_or_missing_scoring_evidence_fails_with_source_context(
    fields, match
):
    with pytest.raises(ValueError, match=match) as error:
        load([row(**fields)])
    assert GAME in str(error.value) and "source row" in str(error.value)


def test_explicit_three_point_value_survives_unfamiliar_style_and_missing_3pt_text():
    event = load([row(subtype="Future Shot Style", shotValue=3)]).items[0]
    assert event.shot_value == event.recorded_points == 3
    assert event.subtype == "Future Shot Style"


@pytest.mark.parametrize(
    "kind,subtype",
    [
        ("Foul", "Future Foul"),
        ("Turnover", "Future Turnover"),
        ("Violation", "Future Violation"),
        ("Instant Replay", "Overturn Ruling"),
        ("period", "pause"),
        ("Unknown Event", ""),
        ("Heave", "Other"),
        ("Free Throw", "Free Throw 3 of 2"),
        ("Free Throw", "Free Throw Clear Path 1 of 1"),
        ("Free Throw", "Free Throw Bonus"),
    ],
)
def test_unsupported_possession_affecting_semantics_fail(kind, subtype):
    with pytest.raises(ValueError, match="unsupported|invalid"):
        load([row(kind, subtype, description="Smith " + subtype)])


@pytest.mark.parametrize(
    "description",
    [
        "",
        "Smith Unknown Free Throw",
        "Smith Free Throw 1 of 2 (1 PTS)",
        "Smith Free Throw 2 of 2 CANCELLED",
        "Smith Free Throw 2 of 2",
        "MISS Smith Free Throw 2 of 2 (2 PTS)",
    ],
)
def test_ft_outcome_requires_recognized_matching_description(description):
    with pytest.raises(ValueError, match="description"):
        load([row("Free Throw", "Free Throw 2 of 2", description=description)])


def test_split_rows_participant_uncertainty_and_exact_clock_survive():
    shot = row("Missed Shot", clock="PT00M02.80000000000000001S")
    block = row(
        "",
        "",
        actionId=2,
        personId=2,
        teamId=AWAY,
        location="v",
        description="Brown BLOCK (1 BLK)",
        clock=shot["clock"],
    )
    event = load([shot, block]).items[0]
    assert event.group.source_indices == (0, 1)
    assert event.group.primary.seconds_remaining_exact == Decimal("2.80000000000000001")
    assert event.participants.require_player("blocker") == 2
    incomplete = load([shot]).items[0]
    assert incomplete.participants.participants["blocker"].status == "unresolved"
    turnover = load([row("Turnover", "Bad Pass")]).items[0]
    assert turnover.subtype == "Bad Pass"
    assert turnover.participants.participants["stealer"].status == "unresolved"
    with pytest.raises(FrozenInstanceError):
        event.recorded_points = 100


def test_team_heave_excerpt_retains_team_scope_without_fabricating_value():
    payload = json.loads(
        (DATA / "pbp/stats_v3_0042500317_heaves_excerpt.json").read_bytes()
    )
    gid = payload["game"]["gameId"]
    raw = StatsNbaV3PbpLoader(
        gid, SimpleNamespace(load_data=lambda _: V3PbpSourceData(payload))
    )
    events = StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(raw, V3GameContext(gid, 1610612760, 1610612759))
    ).items
    heaves = [e for e in events if e.kind == "team_heave"]
    assert len(heaves) == 2
    assert all(
        e.attribution == "team" and e.shot_value is None and e.recorded_points == 0
        for e in heaves
    )
    assert all(
        e.participants.participants["actor"].status == "not_applicable" for e in heaves
    )


def test_administrative_people_are_not_promoted_to_players():
    event = load(
        [row("Instant Replay", "Support Ruling", personId=133, teamId=0, location="")]
    ).items[0]
    assert event.kind == "replay"
    assert event.attribution is None
    assert event.participants.participants["actor"].status == "not_applicable"


def test_non_scoring_event_cannot_hide_scoring_fields():
    with pytest.raises(ValueError, match="shotValue"):
        load([row("Timeout", "Regular", shotValue=3)])


def test_loader_requires_validated_participant_layer():
    with pytest.raises(TypeError, match="StatsNbaV3ParticipantLoader"):
        StatsNbaV3EventLoader([])
