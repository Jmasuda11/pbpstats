"""Source-backed FT codes and statistics beyond the inherited snapshot inventory."""

import json

import pytest

from pbpstats.data_loader.stats_nba_v3 import V3DecodeError
from pbpstats.data_loader.stats_nba_v3.decoder import (
    FLAGRANT_FREE_THROWS, CLEAR_PATH_FREE_THROWS, TECHNICAL_FREE_THROWS,
)
from tools.parity.free_throw_cases import catalog, v3_inputs, free_throw_snapshot
from tools.parity.reference import ROOT, digest, prepare_reference
from tools.parity.run import worker
from tools.parity.shot_cases import vocabulary
from tools.parity.snapshot import first_difference
from tools.parity.v3_cases import load_synthetic_rows
from tools.parity.vocabulary_evidence import assert_observation, free_throw_vocabulary


CASES = list(catalog())


@pytest.fixture(scope="module")
def results():
    return worker(prepare_reference(), suite="free-throws"), worker(
        ROOT, provider="v3", suite="free-throws"
    )


def test_two_attempt_codes_match_independently_recorded_v2_rows():
    source = vocabulary()["external_recordings"]["external_0021800621"]
    raw = (ROOT / source["path"]).read_bytes()
    assert digest(raw) == source["sha256"]
    table = json.loads(raw)["resultSets"][0]
    for index, event_num, attempt, code in ((323, 485, 1, 18), (324, 486, 2, 19)):
        row = dict(zip(table["headers"], table["rowSet"][index]))
        assert row["EVENTNUM"] == event_num
        assert row["EVENTMSGTYPE"] == 3
        assert row["EVENTMSGACTIONTYPE"] == code == FLAGRANT_FREE_THROWS[attempt, 2]
        assert "Free Throw Flagrant {} of 2".format(attempt) in row["HOMEDESCRIPTION"]


@pytest.mark.parametrize("mapping", free_throw_vocabulary()["mappings"], ids=lambda m: m["subtype"])
def test_all_observed_nba_ft_subtypes_have_independent_recorded_codes(mapping):
    assert_observation(mapping["v2"])
    assert_observation(mapping["v3"])
    old, new = mapping["v2"]["row"], mapping["v3"]["row"]
    assert int(old["EVENTMSGTYPE"]) == 3
    assert int(old["EVENTMSGACTIONTYPE"]) == mapping["v2_action_type"]
    assert (old["HOMEDESCRIPTION"] or old["VISITORDESCRIPTION"]).split(" (")[0].endswith(mapping["subtype"])
    assert new["subType"] == mapping["subtype"]
    assert new["actionType"] == "Free Throw"


@pytest.mark.parametrize("index", range(len(CASES)), ids=[c["name"] for c in CASES])
def test_free_throw_properties_and_statistics_match_original(results, index):
    old, new = (r["results"][index] for r in results)
    assert old["status"] == new["status"] == "ok", (old, new)
    assert old["credits"] == new["credits"]
    assert first_difference(old["snapshot"], new["snapshot"]) is None
    assert '"unavailable"' not in json.dumps(new["snapshot"])
    details = new["snapshot"]["free_throw_details"]
    case = CASES[index]
    assert [f["properties"]["event_action_type"] for f in details] == case["v2_action_types"]
    for attempt, ft in enumerate(details, 1):
        props = ft["properties"]
        if case["category"] == "Flagrant":
            assert props["is_flagrant_ft"] and not props["is_end_ft"]
            # Original quirks: 18/19/28/29 are not first/end attempts.
            assert props["is_first_ft"] == (case["total"] in (1, 3) and attempt == 1)
            assert props["free_throw_type"] == (
                "1 Shot Away From Play" if case["total"] == 1 else f"{case['total']} Shot Flagrant"
            )
        elif case["category"] == "Clear Path":
            assert not props["is_first_ft"] and not props["is_end_ft"]
            assert props["free_throw_type"] == "2 Shot Clear Path"
        elif case["category"] == "Technical":
            assert props["is_technical_ft"] and props["free_throw_type"] == "Technical"
            assert ft["foul"] is None
        if CASES[index]["substitute"] and props["is_made"]:
            plusminus = {
                s["player_id"]: s
                for s in ft["event_stats"]
                if s["stat_key"] == "PlusMinus"
            }
            assert 2 in plusminus and 6 not in plusminus
            assert plusminus[2]["lineup_id"] == "1-2-3-4-5"


def test_regression_detects_old_second_attempt_code_and_extra_trip_stat(
    results, monkeypatch
):
    index = next(i for i, c in enumerate(CASES) if c["name"] == "flagrant_2_MM_sub1")
    expected = results[0]["results"][index]["snapshot"]
    monkeypatch.setitem(FLAGRANT_FREE_THROWS, (2, 2), 20)
    changed = free_throw_snapshot(load_synthetic_rows(v3_inputs(CASES[index])))
    assert first_difference(expected, changed) is not None
    old_ft, changed_ft = (
        expected["free_throw_details"][1],
        changed["free_throw_details"][1],
    )
    assert not old_ft["properties"]["is_first_ft"]
    assert changed_ft["properties"]["is_first_ft"]
    assert not any("Free Throw Trips" in s["stat_key"] for s in old_ft["event_stats"])
    assert any("Free Throw Trips" in s["stat_key"] for s in changed_ft["event_stats"])


@pytest.mark.parametrize("name,table,attempt,wrong_code", [
    ("clear_path_2_MM_sub1", CLEAR_PATH_FREE_THROWS, (1, 2), 17),
    ("clear_path_2_MM_sub1", CLEAR_PATH_FREE_THROWS, (2, 2), 18),
    ("technical_2_MM_sub1", TECHNICAL_FREE_THROWS, (1, 2), 16),
    ("technical_2_MM_sub1", TECHNICAL_FREE_THROWS, (2, 2), 16),
    ("flagrant_3_MMM_sub1", FLAGRANT_FREE_THROWS, (1, 3), 13),
])
def test_recorded_ft_comparison_detects_inherited_and_generic_code_drift(
    results, monkeypatch, name, table, attempt, wrong_code
):
    index = next(i for i, case in enumerate(CASES) if case["name"] == name)
    monkeypatch.setitem(table, attempt, wrong_code)
    actual = free_throw_snapshot(load_synthetic_rows(v3_inputs(CASES[index])))
    assert first_difference(results[0]["results"][index]["snapshot"], actual) is not None


@pytest.mark.parametrize("subtype", ["Free Throw Flagrant 1 of 4", "Free Throw Clear Path 1 of 3", "Free Throw Technical 1 of 3", "Free Throw Technical 1 of 1"])
def test_unrecorded_ft_numbering_stays_explicitly_blocked(subtype):
    rows = v3_inputs(CASES[0])
    ft = next(r for r in rows if r["actionType"] == "Free Throw")
    ft["description"] = ft["description"].replace(ft["subType"], subtype)
    ft["subType"] = subtype
    with pytest.raises(V3DecodeError, match="Unsupported|Invalid"):
        load_synthetic_rows(rows)


def test_expanded_ft_checks_do_not_enable_incomplete_foul_drawn_statistics():
    loaded = load_synthetic_rows(v3_inputs(CASES[0]))
    assert loaded.decoded.unknown_attribution
    with pytest.raises(V3DecodeError, match="attribution completeness"):
        loaded.event_stats
