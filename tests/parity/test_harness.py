"""The comparison must find changes, not merely agree with itself."""

from copy import deepcopy
import hashlib
import json

import pytest

from tools.parity.reference import ROOT, prepare_reference
from tools.parity.run import compare, worker
from tools.parity.snapshot import first_difference, scalar


@pytest.fixture(scope="module")
def reference_results():
    return worker(prepare_reference())


def test_candidate_v2_matches_frozen_original(reference_results):
    result = compare(reference_results, worker(ROOT))
    assert result["cases"] == 145
    assert result["statuses"] == {"same": 145}


@pytest.mark.parametrize(
    "mutation", ("boundary", "lineup", "count", "missing_case", "rejection")
)
def test_comparison_detects_deliberate_drift(reference_results, mutation):
    changed = deepcopy(reference_results)
    case = changed["results"][0]
    if mutation == "boundary":
        case["snapshot"]["possessions"][0]["events"].pop()
    elif mutation == "lineup":
        case["snapshot"]["events"][0]["lineups"]["1610612761"][0] = 999
    elif mutation == "count":
        case["snapshot"]["possessions"][0]["counted"] = False
    elif mutation == "missing_case":
        changed["results"].pop(0)
    else:
        case.update(status="error", error="Missing evidence")
    result = compare(reference_results, changed)
    assert result["cases"] == 145
    assert result["statuses"].get("same", 0) == 144


def test_numeric_normalization_preserves_fractional_threshold():
    assert scalar(2.0) == 2
    assert scalar(2.8) != scalar(2)
    assert (
        first_difference({"clock": scalar(2.8)}, {"clock": scalar(2)})["path"]
        == "$.clock"
    )


def test_rejections_are_not_successes():
    errors = {
        "results": [{"name": "bad", "status": "error", "error": "Missing evidence"}]
    }
    assert compare(errors, errors)["statuses"] == {"rejected": 1}


def test_scenario_definitions_match_recorded_provenance():
    manifest = json.loads((ROOT / "tests/parity/manifest.json").read_text())
    assert (
        hashlib.sha256((ROOT / "tools/parity/scenarios.py").read_bytes()).hexdigest()
        == manifest["scenarios"]["sha256"]
    )


def test_three_archived_games_match_without_mutating_fixtures():
    reference = prepare_reference()
    fixtures = reference / "tests/data"
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures.rglob("*.json")
    }
    original = worker(reference, suite="archived", fixtures=fixtures)
    candidate = worker(ROOT, suite="archived", fixtures=fixtures)
    result = compare(original, candidate)
    assert result["statuses"] == {"same": 3}
    assert sum(len(r["credits"]["groups"]) for r in original["results"]) == 649
    assert before == {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures.rglob("*.json")
    }
