"""Untimed clock joins require corroborating period and scoring evidence."""

import json
import socket
from types import SimpleNamespace

import pytest
import test_stats_v3_leagues as leagues
import test_stats_v3_shot_zones as zones

from pbpstats.data_loader.stats_nba_v3.shot_zones import StatsNbaV3ShotZoneLoader


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("clock evidence attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def recorded():
    _, events = zones.classified("2022500001")
    payload = json.loads((zones.DATA / "2022500001-live.json").read_bytes())
    return events, payload


def rebuild(events, rows, complete=True):
    raw = leagues.StatsNbaV3PbpLoader(
        events.game_id,
        SimpleNamespace(
            load_data=lambda _: leagues.V3PbpSourceData(
                {"game": {"gameId": events.game_id, "actions": rows}}
            )
        ),
    )
    return leagues.StatsNbaV3EventLoader(
        leagues.StatsNbaV3ParticipantLoader(
            raw, events.context, snapshot_complete=complete
        )
    )


def native_rows(events):
    return [
        r.data
        for r in sorted(
            (r for e in events.items for r in e.group.rows), key=lambda r: r.order
        )
    ]


def test_target_score_join_preserves_clocks_sources_and_possessions(recorded):
    events, payload = recorded
    original_native = native_rows(events)
    source = zones.evidence(payload)
    loaded = StatsNbaV3ShotZoneLoader(events, source).require_complete()
    by_action = {r.action_number: r for r in loaded.items}
    assert by_action[737].shot_type == "Corner3"
    assert by_action[746].shot_type == "Arc3"
    assert by_action[737].native_clock == "PT97M19.00S"
    assert by_action[746].native_clock == "PT97M07.00S"
    assert {
        r.action_number for r in loaded.items if r.clock_basis == "untimed_sequence"
    } == {737, 746}
    assert all(
        r.live_clock == "PT00M00.00S"
        for r in loaded.items
        if r.clock_basis == "untimed_sequence"
    )
    assert all(r.clock_basis == "exact" for r in loaded.items if r.action_number < 737)
    assert source.data == payload
    assert native_rows(events) == original_native
    lineups = leagues.lineups(events, zones.lineup_evidence(events.game_id))
    result = leagues.StatsNbaV3PossessionLoader(lineups, shot_zones=loaded)
    baseline = leagues.StatsNbaV3PossessionLoader(lineups)
    assert result.base_stats == baseline.base_stats
    assert result.counts_by_team == baseline.counts_by_team
    assert [e.clock for e in result.events] == [e.clock for e in baseline.events]
    assert [p.possession_start_type for p in result.items]


@pytest.mark.parametrize(
    "change",
    [
        "flag_missing",
        "flag_false",
        "flag_integer",
        "period_type",
        "nonzero_clock",
        "period_float",
        "later_period_float",
        "period_none",
        "start_missing",
        "end_missing",
        "marker_mismatch",
        "start_score",
        "end_score",
        "attempt_missing",
        "attempt_order",
        "attempt_before_start",
        "player",
        "team",
        "outcome",
        "points",
        "score_on_miss",
        "free_throw",
        "second_overtime",
    ],
)
def test_live_period_cannot_waive_clock_comparison_without_corroboration(
    recorded, change
):
    events, payload = recorded
    rows = payload["game"]["actions"]
    by_id = {r["actionNumber"]: r for r in rows}
    metadata_changes = {
        "flag_false": (737, "isTargetScoreLastPeriod", False),
        "flag_integer": (737, "isTargetScoreLastPeriod", 1),
        "period_type": (737, "periodType", "REGULAR"),
        "nonzero_clock": (727, "clock", "PT00M01S"),
        "period_float": (727, "period", 5.0),
        "later_period_float": (727, "period", 6.0),
        "period_none": (727, "period", None),
    }
    if change in metadata_changes:
        number, key, value = metadata_changes[change]
        by_id[number][key] = value
    elif change == "flag_missing":
        del by_id[737]["isTargetScoreLastPeriod"]
    elif change in ("start_missing", "end_missing", "attempt_missing"):
        rows.remove(
            by_id[
                {"start_missing": 721, "end_missing": 761, "attempt_missing": 728}[
                    change
                ]
            ]
        )
    elif change == "marker_mismatch":
        by_id[721]["actionNumber"] = 9999
    elif change == "start_score":
        by_id[721]["scoreHome"] = "111"
    elif change == "end_score":
        by_id[761]["scoreAway"] = "120"
    elif change == "attempt_order":
        first, second = rows.index(by_id[727]), rows.index(by_id[728])
        rows[first], rows[second] = rows[second], rows[first]
    elif change == "attempt_before_start":
        rows.remove(by_id[727])
        rows.insert(rows.index(by_id[721]), by_id[727])
    elif change == "player":
        by_id[727]["personId"] = by_id[737]["personId"]
    elif change == "team":
        by_id[727]["teamId"] = by_id[737]["teamId"]
    elif change == "outcome":
        by_id[728]["shotResult"] = "Made"
    elif change == "points":
        by_id[727]["scoreHome"] = "115"
    elif change == "score_on_miss":
        by_id[746]["scoreAway"] = "118"
    elif change == "free_throw":
        by_id[758]["shotResult"] = "Made"
    elif change == "second_overtime":
        rows.append(dict(by_id[761], actionNumber=9999, period=6))
    loaded = StatsNbaV3ShotZoneLoader(events, zones.evidence(payload))
    failed = [r for r in loaded.items if not r.validated]
    assert {r.action_number for r in failed} == {737, 746}
    assert all("clock conflicts with native shot" in r.issues for r in failed)
    assert all(r.clock_basis is None for r in failed)
    with pytest.raises(ValueError, match="untimed"):
        loaded.require_complete()


@pytest.mark.parametrize(
    "change",
    [
        "incomplete",
        "start_missing",
        "end_missing",
        "opening_clock",
        "clock_order",
        "start_score",
        "end_score",
        "last_clock",
        "score_on_make",
        "second_overtime",
    ],
)
def test_native_period_must_be_complete_and_coherent(recorded, change):
    events, payload = recorded
    rows = native_rows(events)
    by_id = {r["actionNumber"]: r for r in rows if r["actionType"]}
    if change in ("start_missing", "end_missing"):
        rows.remove(by_id[721 if change == "start_missing" else 761])
    elif change == "opening_clock":
        by_id[721]["clock"] = "PT98M59S"
    elif change == "clock_order":
        by_id[730]["clock"] = "PT98M45S"
    elif change == "start_score":
        by_id[721]["scoreHome"] = "111"
    elif change == "end_score":
        by_id[761]["scoreAway"] = "120"
    elif change == "last_clock":
        by_id[761]["clock"] = "PT96M26S"
    elif change == "score_on_make":
        by_id[730]["scoreHome"] = "117"
    elif change == "second_overtime":
        rows.append(dict(by_id[761], actionId=9999, actionNumber=9999, period=6))
    changed = rebuild(events, rows, complete=change != "incomplete")
    loaded = StatsNbaV3ShotZoneLoader(changed, zones.evidence(payload))
    assert {r.action_number for r in loaded.items if not r.validated} == {737, 746}
    with pytest.raises(ValueError, match="untimed"):
        loaded.require_complete()


@pytest.mark.parametrize("before_start", [False, True])
def test_unknown_field_goal_cannot_disappear_from_clock_join(recorded, before_start):
    events, payload = recorded
    rows = payload["game"]["actions"]
    original = next(r for r in rows if r["actionNumber"] == 727)
    anchor = next(
        r for r in rows if r["actionNumber"] == (721 if before_start else 746)
    )
    rows.insert(
        rows.index(anchor), dict(original, actionNumber=9999, actionType="unknown shot")
    )
    loaded = StatsNbaV3ShotZoneLoader(events, zones.evidence(payload))
    with pytest.raises(ValueError, match="untimed"):
        loaded.require_complete()
    assert {r.action_number for r in loaded.items if not r.validated} == {737, 746}


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("xLegacy", -227, "xLegacy conflicts"),
        ("areaDetail", "24+ Right", "area and areaDetail conflict"),
    ],
)
def test_clock_match_never_waives_coordinate_or_label_checks(
    recorded, field, value, issue
):
    events, payload = recorded
    row = next(r for r in payload["game"]["actions"] if r["actionNumber"] == 737)
    row[field] = value
    loaded = StatsNbaV3ShotZoneLoader(events, zones.evidence(payload))
    with pytest.raises(ValueError, match=issue):
        loaded.require_complete()
    result = next(r for r in loaded.items if r.action_number == 737)
    assert result.clock_basis == "untimed_sequence" and result.shot_type is None


@pytest.mark.parametrize(
    "gid,period",
    [
        ("0022500001", 5),
        ("1022600001", 5),
        ("2022100001", 5),
        ("2022500001", 4),
    ],
)
def test_zero_clock_exception_is_excluded_from_timed_periods(gid, period):
    events, payload = zones.sample(gid)
    rows = native_rows(events)
    for row, clock in zip(rows, ["PT05M00S", "PT04M00S", "PT03M00S", "PT00M00S"]):
        row.update(period=period, clock=clock)
    events = rebuild(events, rows)
    payload["game"]["actions"][0].update(
        period=period,
        clock="PT00M00S",
        periodType="OVERTIME",
        isTargetScoreLastPeriod=True,
    )
    loaded = StatsNbaV3ShotZoneLoader(events, zones.evidence(payload))
    with pytest.raises(ValueError, match="clock conflicts"):
        loaded.require_complete()
    assert loaded.items[0].clock_basis is None
