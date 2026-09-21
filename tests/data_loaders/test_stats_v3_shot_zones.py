"""Independent feed joins, explicit conflicts and possession integration offline."""

import hashlib
import json
import socket
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_stats_v3_leagues as leagues
import test_stats_v3_lineups as synthetic
import test_stats_v3_possessions as plays
from v3_league_fixtures import classified, lineup_evidence

from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader
from pbpstats.data_loader.stats_nba_v3.shot_zones import (
    StatsNbaV3ShotZoneLoader,
    V3LiveShotEvidence,
)

DATA = Path(__file__).parents[1] / "data/v3/shot_zones"
MANIFEST = json.loads((DATA / "manifest.json").read_bytes())["games"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("shot-zone validation attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def evidence(payload):
    return V3LiveShotEvidence(json.dumps(payload).encode(), "synthetic live evidence")


def sample(gid="1022600001", *, context=None):
    start = dict(synthetic.start(), clock="PT10M00S" if gid[:2] == "10" else "PT12M00S")
    shot = dict(
        synthetic.shot(1, "PT09M00S"),
        shotValue=3,
        description="Player1 3PT Jump Shot (3 PTS)",
        xLegacy=230,
        yLegacy=50,
    )
    events = leagues.facts(
        [start, shot, synthetic.shot(11, "PT08M00S", team=plays.AWAY), synthetic.end()],
        gid,
        context,
    )
    live = dict(
        actionNumber=2,
        period=1,
        clock="PT09M00.00S",
        teamId=plays.HOME,
        personId=1,
        actionType="3pt",
        isFieldGoal=1,
        shotResult="Made",
        xLegacy=230,
        yLegacy=50,
        area="Above the Break 3",
        areaDetail="Above the Break 3",
    )
    return events, {"game": {"gameId": gid, "actions": [live]}}


@pytest.mark.parametrize("record", MANIFEST, ids=lambda r: r["game_id"])
def test_recorded_join_and_possession_labels(record):
    gid = record["game_id"]
    raw = (DATA / record["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record["sha256"]
    source = V3LiveShotEvidence.from_file(DATA / record["file"], source=record["url"])
    assert source.source_bytes == raw and source.sha256 == record["sha256"]
    _, events = classified(gid)
    zones = StatsNbaV3ShotZoneLoader(events, source)
    expected = {
        "0022500341": (69, 69, {"Arc3": 52, "Corner3": 17}),
        "1022600100": (69, 40, {"Arc3": 37, "Corner3": 3}),
        "1022600101": (51, 41, {"Arc3": 38, "Corner3": 3}),
        "2022500001": (61, 61, {"Arc3": 48, "Corner3": 13}),
    }[gid]
    assert (len(zones.items), sum(r.validated for r in zones.items)) == expected[:2]
    assert Counter(r.shot_type for r in zones.items if r.validated) == expected[2]
    lineups = leagues.lineups(events, lineup_evidence(gid))
    result = StatsNbaV3PossessionLoader(lineups, shot_zones=zones)
    baseline = StatsNbaV3PossessionLoader(lineups)
    assert [e.score for e in result.events] == [e.score for e in baseline.events]
    assert [e.base_stats for e in result.events] == [
        e.base_stats for e in baseline.events
    ]
    successful_starts = 0
    for event in result.events:
        if event.facts.kind != "field_goal" or event.shot_value != 3:
            continue
        zone = zones.by_source_index[event.facts.group.primary.order]
        if zone.validated:
            assert event.shot_type == zone.shot_type
        else:
            with pytest.raises(ValueError, match="shot zones.*source row"):
                event.shot_type
    for possession in result.items:
        try:
            possession.possession_start_type
            successful_starts += 1
        except ValueError as error:
            assert "shot zones" in str(error)
    assert successful_starts > 0
    if gid in ("0022500341", "2022500001"):
        assert zones.require_complete() is zones
        assert successful_starts == len(result.items)
    else:
        with pytest.raises(ValueError, match="source row"):
            zones.require_complete()


def test_recorded_conflicts_are_not_repaired_or_hidden():
    _, events = classified("1022600100")
    zones = StatsNbaV3ShotZoneLoader(
        events, V3LiveShotEvidence.from_file(DATA / "1022600100-live.json")
    )
    records = {r.action_number: r for r in zones.items}
    assert records[127].issues == ("area and areaDetail conflict",)
    assert "xLegacy conflicts with native shot" in records[403].issues
    assert records[24].shot_type == "Corner3"


@pytest.mark.parametrize("gid", ["0022500001", "1022600001", "2022500001"])
def test_labels_use_agreeing_sources_not_nba_coordinate_cutoff(gid):
    events, payload = sample(gid)
    zones = StatsNbaV3ShotZoneLoader(events, evidence(payload)).require_complete()
    assert zones.require_zone(1) == "Arc3"  # y=50 would otherwise use NBA Corner3.
    inputs = dict(
        schema_version=1,
        game_id=gid,
        **dict(zones.fingerprints),
        periods=[synthetic.period_evidence(1)],
        batches=[],
    )
    result = StatsNbaV3PossessionLoader(
        leagues.lineups(events, inputs), shot_zones=zones
    )
    assert result.events[1].shot_type == "Arc3"
    assert result.items[1].possession_start_type == "OffArc3Make"


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("personId", 11, "personId conflicts"),
        ("personId", True, "personId conflicts"),
        ("teamId", plays.AWAY, "teamId conflicts"),
        ("period", 2, "period conflicts"),
        ("clock", "PT08M59S", "clock conflicts"),
        ("clock", "PT08M60S", "clock conflicts"),
        ("clock", None, "clock conflicts"),
        ("shotResult", "Missed", "shotResult conflicts"),
        ("actionType", "2pt", "actionType conflicts"),
        ("isFieldGoal", True, "isFieldGoal conflicts"),
        ("xLegacy", 231, "xLegacy conflicts"),
        ("yLegacy", 51, "yLegacy conflicts"),
        ("xLegacy", None, "finite coordinates"),
        ("xLegacy", True, "finite coordinates"),
        ("area", "Left Corner 3", "area and areaDetail conflict"),
        ("areaDetail", "Right Corner 3", "area and areaDetail conflict"),
        ("areaDetail", "Mid-Range", "areaDetail is missing or unsupported"),
        ("area", "Unknown", "area is missing or unsupported"),
        ("areaDetail", None, "areaDetail is missing or unsupported"),
    ],
)
def test_conflicting_or_incomplete_rows_raise_on_dependent_access(field, value, issue):
    events, payload = sample()
    payload["game"]["actions"][0][field] = value
    zones = StatsNbaV3ShotZoneLoader(events, evidence(payload))
    assert zones.items[0].shot_type is None
    with pytest.raises(ValueError, match=issue):
        zones.require_zone(1)
    with pytest.raises(ValueError, match=issue):
        zones.require_complete()


def test_opposite_corner_labels_conflict():
    events, payload = sample()
    payload["game"]["actions"][0].update(
        area="Left Corner 3", areaDetail="Right Corner 3"
    )
    with pytest.raises(ValueError, match="area and areaDetail conflict"):
        StatsNbaV3ShotZoneLoader(events, evidence(payload)).require_complete()


def test_missing_rows_do_not_fall_back_to_coordinates():
    events, payload = sample("0022500001")
    payload["game"]["actions"] = []
    zones = StatsNbaV3ShotZoneLoader(events, evidence(payload))
    inputs = dict(
        schema_version=1,
        game_id=events.game_id,
        **dict(zones.fingerprints),
        periods=[synthetic.period_evidence(1)],
        batches=[],
    )
    result = StatsNbaV3PossessionLoader(
        leagues.lineups(events, inputs), shot_zones=zones
    )
    with pytest.raises(ValueError, match="missing live shot"):
        result.items[1].possession_start_type
    with pytest.raises(ValueError, match="no three-point zone evidence"):
        zones.require_zone(0)


@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize(
    "area,zone", [("Left Corner 3", "Corner3"), ("Above the Break 3", "Arc3")]
)
def test_wnba_rebound_start_labels_use_the_validated_missed_shot(blocked, area, zone):
    _, payload = sample()
    shot = dict(
        plays.miss("PT09M00S"),
        shotValue=3,
        xLegacy=230,
        yLegacy=50,
        description="MISS Player1 3PT Jump Shot",
    )
    events = leagues.facts(
        [
            dict(synthetic.start(), clock="PT10M00S"),
            shot,
            plays.rebound("PT08M59S"),
            synthetic.shot(11, "PT08M00S", team=plays.AWAY),
            synthetic.end(),
        ],
        "1022600001",
    )
    if blocked:
        rows = [e.group.primary.data for e in events.items]
        rows.insert(
            2,
            dict(
                synthetic.row(
                    "", "", "PT09M00S", 12, plays.AWAY, "Player12 BLOCK (1 BLK)"
                ),
                actionNumber=2,
                actionId=6,
            ),
        )
        raw = leagues.StatsNbaV3PbpLoader(
            events.game_id,
            SimpleNamespace(
                load_data=lambda _: leagues.V3PbpSourceData(
                    {"game": {"gameId": events.game_id, "actions": rows}}
                )
            ),
        )
        events = leagues.StatsNbaV3EventLoader(
            leagues.StatsNbaV3ParticipantLoader(
                raw, events.context, snapshot_complete=True
            )
        )
    payload["game"]["actions"][0].update(
        shotResult="Missed", area=area, areaDetail=area
    )
    zones = StatsNbaV3ShotZoneLoader(events, evidence(payload))
    inputs = dict(
        schema_version=1,
        game_id=events.game_id,
        **dict(zones.fingerprints),
        periods=[synthetic.period_evidence(1)],
        batches=[],
    )
    result = StatsNbaV3PossessionLoader(
        leagues.lineups(events, inputs), shot_zones=zones
    )
    ending = "Block" if blocked else "Miss"
    assert result.items[1].possession_start_type == f"Off{zone}{ending}"


@pytest.mark.parametrize(
    "change,issue",
    [
        ("game", "gameId conflicts"),
        ("actions", "actions must be an array"),
        ("duplicate", "duplicate actionNumber"),
        ("invalid_number", "invalid or duplicate actionNumber"),
        ("extra_shot", "extraneous live three-point"),
        ("extra_known", "conflicts with native event kind"),
        ("non_object", "action must be an object"),
    ],
)
def test_structural_ambiguity_fails_at_load(change, issue):
    events, payload = sample()
    game = payload["game"]
    if change == "game":
        game["gameId"] = "1022600002"
    elif change == "actions":
        game["actions"] = {}
    elif change == "duplicate":
        game["actions"] *= 2
    elif change == "invalid_number":
        game["actions"][0]["actionNumber"] = True
    elif change in ("extra_shot", "extra_known"):
        game["actions"].append(
            dict(game["actions"][0], actionNumber=999 if change == "extra_shot" else 3)
        )
    else:
        game["actions"].append(None)
    with pytest.raises(ValueError, match=issue):
        StatsNbaV3ShotZoneLoader(events, evidence(payload))


@pytest.mark.parametrize("change", ["context", "snapshot"])
def test_evidence_cannot_be_attached_to_changed_lineup_inputs(change):
    events, payload = sample()
    zones = StatsNbaV3ShotZoneLoader(events, evidence(payload))
    if change == "context":
        context = replace(events.context, roster_source="different source")
        other, _ = sample(context=context)
    else:
        rows = [e.group.primary.data for e in events.items]
        rows[1]["xLegacy"] = 231
        other = leagues.facts(rows, events.game_id)
    inputs = dict(
        schema_version=1,
        game_id=events.game_id,
        **leagues.lineup_fingerprints(other),
        periods=[synthetic.period_evidence(1)],
        batches=[],
    )
    with pytest.raises(ValueError, match="fingerprints do not match"):
        StatsNbaV3PossessionLoader(leagues.lineups(other, inputs), shot_zones=zones)


def test_provenance_and_results_preserve_original_evidence(tmp_path):
    events, payload = sample()
    source = evidence(payload)
    original = source.source_bytes
    source.data["game"]["actions"][0]["area"] = "Left Corner 3"
    zones = StatsNbaV3ShotZoneLoader(events, source)
    assert source.source_bytes == original and zones.require_zone(1) == "Arc3"
    with pytest.raises(FrozenInstanceError):
        zones.items[0].shot_type = "Corner3"
    with pytest.raises(TypeError):
        zones.by_source_index[1] = None
    with pytest.raises(FileNotFoundError):
        V3LiveShotEvidence.from_file(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="provenance"):
        V3LiveShotEvidence(original, " ")


@pytest.mark.parametrize(
    "raw",
    [b"{} {}", b'{"game":{},"game":{}}', b'{"n":NaN}', b'{"n":1e999}', b"[]", b"\xff"],
)
def test_malformed_evidence_fails_with_source_location(raw):
    with pytest.raises(ValueError, match="Live shot evidence recorded.json"):
        V3LiveShotEvidence(raw, "recorded.json")
