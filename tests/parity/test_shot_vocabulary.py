"""Source-backed action codes, complete-input behavior, and explicit limits."""

from copy import deepcopy
import json
import re

import pytest

from pbpstats.data_loader.stats_nba_v3 import V3DecodeError
from pbpstats.data_loader.stats_nba_v3.decoder import SHOT_CODES
from tools.parity.reference import ROOT, prepare_reference
from tools.parity.run import worker
from tools.parity.shot_cases import catalog, shot_snapshot, v3_inputs, vocabulary
from tools.parity.snapshot import first_difference
from tools.parity.v3_cases import load_synthetic_rows
from tools.parity.vocabulary_evidence import assert_observation


CASES = list(catalog())


@pytest.fixture(scope="module")
def sources():
    return {"reference": prepare_reference(), "prior": prepare_reference("prior")}


@pytest.fixture(scope="module")
def results(sources):
    return worker(sources["reference"], suite="shots"), worker(
        ROOT, provider="v3", suite="shots"
    )


@pytest.mark.parametrize(
    "mapping", vocabulary()["mappings"], ids=lambda m: m["subtype"]
)
def test_vocabulary_observations_match_pinned_source_bytes(sources, mapping):
    manifest = json.loads((ROOT / "tests/parity/manifest.json").read_bytes())
    for version in ("reference", "prior"):
        assert vocabulary()[version + "_revision"] == manifest[version + "_revision"]
    for version in ("v2", "v3"):
        assert_observation(mapping[version])
    old, new = mapping["v2"]["row"], mapping["v3"]["row"]
    assert int(old["EVENTMSGACTIONTYPE"]) == mapping["v2_action_type"]
    assert int(old["EVENTMSGTYPE"]) in (1, 2)
    assert new["subType"] == mapping["subtype"]
    assert new["actionType"] in ("Made Shot", "Missed Shot")

    # Reviewed labels describe the same mechanics across separate recordings.
    def mechanics(label):
        return re.sub(r" shot$", "", label.casefold().replace("jumper", "jump shot"))

    label = mechanics(mapping["subtype"])
    assert any(
        mechanics(description.split(" (")[0]).endswith(label)
        for description in (old["HOMEDESCRIPTION"], old["VISITORDESCRIPTION"])
        if description
    )
    assert mechanics(new["description"].split(" (")[0]).endswith(label)


@pytest.mark.parametrize("index", range(len(CASES)), ids=[c["name"] for c in CASES])
def test_complete_shot_facts_match_original(results, index):
    original, candidate = results
    old, new = original["results"][index], candidate["results"][index]
    assert old["status"] == "ok", old
    assert new["status"] == "ok", new
    assert old["name"] == new["name"] == CASES[index]["name"]
    assert old["credits"] == new["credits"]
    assert first_difference(old["snapshot"], new["snapshot"]) is None
    assert '"unavailable"' not in json.dumps(new["snapshot"])
    shot = new["snapshot"]["shot_details"][0]
    assert shot["event_action_type"] == CASES[index]["v2_action_type"]
    assert (shot["locX"], shot["locY"], shot["distance"], shot["shot_type"]) == (
        10,
        15,
        "1.8",
        "AtRim",
    )
    outcome = CASES[index]["outcome"]
    stats = {
        (s["player_id"], s["stat_key"]): s["stat_value"] for s in shot["event_stats"]
    }
    if outcome == "assisted":
        assert shot["shot_data"]["AssistPlayerId"] == 2
        assert stats[2, "AtRimAssists"] == 1
    elif outcome == "blocked":
        assert shot["shot_data"]["BlockPlayerId"] == 11
        assert stats[11, "BlockedAtRim"] == 1
        assert stats[1, "AtRimBlocked"] == 1
    elif outcome == "made":
        assert shot["shot_data"]["Assisted"] is False
        assert stats[1, "UnassistedAtRim"] == 1
    else:
        assert shot["shot_data"]["Blocked"] is False
        assert stats[1, "MissedAtRim"] == 1


def test_snapshot_detects_wrong_action_code_even_when_credits_agree(
    results, monkeypatch
):
    old = results[0]["results"][0]
    monkeypatch.setitem(SHOT_CODES, CASES[0]["subtype"], 1)
    actual = shot_snapshot(load_synthetic_rows(v3_inputs(CASES[0])))
    difference = first_difference(old["snapshot"], actual)
    assert difference["path"] == "$.shot_details[0].event_action_type"


@pytest.mark.parametrize("kind", ("location", "assist", "block"))
def test_complete_shot_snapshot_detects_fact_drift(results, kind):
    index = {"location": 0, "assist": 1, "block": 3}[kind]
    rows = v3_inputs(CASES[index])
    if kind == "location":
        rows[1]["xLegacy"] = 250
    elif kind == "assist":
        rows[1]["description"] = rows[1]["description"].replace(
            "Player2 1 AST", "Player3 1 AST"
        )
    else:
        rows[2].update(personId=12, description="Player12 BLOCK (1 BLK)")
    actual = shot_snapshot(load_synthetic_rows(rows))
    assert (
        first_difference(results[0]["results"][index]["snapshot"], actual) is not None
    )


@pytest.mark.parametrize(
    "subtype",
    [
        "Running Reverse Layup Shot Extra",
        "Reverse Dunk",
        "Driving Dunk Shot Extra",
        "Dunk",
    ],
)
def test_unreviewed_related_vocabulary_still_rejected(subtype):
    rows = v3_inputs(CASES[0])
    rows[1]["subType"] = subtype
    with pytest.raises(V3DecodeError, match="Unsupported shot subtype"):
        load_synthetic_rows(rows)


def test_detailed_statistics_remain_gated_and_source_rows_preserved():
    rows = v3_inputs(CASES[3])
    original = deepcopy(rows)
    loaded = load_synthetic_rows(rows)
    assert loaded.decoded.raw_rows == rows == original
    assert sorted(
        i for event in loaded.events for i in event.v3_source_indices
    ) == list(range(len(rows)))
    assert loaded.capabilities["detailed_event_stats"] == "unavailable"
    with pytest.raises(V3DecodeError, match="attribution completeness"):
        loaded.event_stats


@pytest.mark.parametrize("alias", vocabulary()["unresolved_aliases"], ids=lambda a: a["subtype"])
def test_historical_aliases_are_preserved_as_unresolved_evidence(alias):
    assert_observation(alias["v2"])
    assert int(alias["v2"]["row"]["EVENTMSGACTIONTYPE"]) == alias["also_recorded_code"]
    assert alias["current_constructor_code"] == SHOT_CODES[alias["subtype"]]
    assert alias["also_recorded_code"] != alias["current_constructor_code"]


def test_recorded_mapping_inventory_covers_every_supported_shot_subtype():
    reviewed = {m["subtype"]: m["v2_action_type"] for m in vocabulary()["mappings"]}
    assert len(reviewed) == len(vocabulary()["mappings"])
    assert reviewed == SHOT_CODES
