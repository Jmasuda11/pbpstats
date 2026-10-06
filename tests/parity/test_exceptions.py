"""Failures must match the pinned oracle at the declared parser boundary."""

from copy import deepcopy
import ast
import hashlib
import json
import socket

import pytest

from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3DecodeError,
    V3Overrides,
    V3EventOrder,
)
from tools.parity.exception_cases import (
    BAD,
    catalog,
    override_bytes,
    provider_payload,
    v3_inputs,
)
from tools.parity.exceptions import EXCEPTION_MODULES, MATCHES, compare_exceptions
from tools.parity.reference import ROOT, prepare_reference
from tools.parity.run import worker


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Exception fixture attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(scope="module")
def compared():
    reference = worker(prepare_reference(), suite="exceptions")
    candidate = worker(ROOT, provider="v3", suite="exceptions")
    return reference, candidate


@pytest.mark.parametrize("name", [case["name"] for case in catalog()])
def test_declared_exception_or_recovery_matches_original(compared, name):
    report = compare_exceptions(*compared)
    case = next(r for r in report["results"] if r["name"] == name)
    assert case["status"] in MATCHES, case


@pytest.mark.parametrize(
    "mutation",
    [
        "type",
        "module",
        "message",
        "swallowed",
        "identical_crash",
        "expectation",
        "fixture",
        "boundary",
        "group",
        "missing",
        "unknown",
    ],
)
def test_exception_comparator_detects_drift_and_identical_unexpected_crashes(
    compared, mutation
):
    left, right = deepcopy(compared)
    result = next(r for r in right["results"] if r["name"] == "back_to_back_scores")
    if mutation in ("type", "module", "message"):
        result["outcome"][mutation] = "changed"
    elif mutation == "swallowed":
        result["outcome"] = dict(kind="return", value={})
    elif mutation == "identical_crash":
        failure = dict(
            kind="exception", type="KeyError", module="builtins", message="unexpected"
        )
        result["outcome"] = failure
        next(r for r in left["results"] if r["name"] == result["name"])[
            "outcome"
        ] = failure
    elif mutation == "expectation":
        result["expected_exception"] = None
    elif mutation == "fixture":
        result["fixture_sha256"] = "changed"
    elif mutation == "boundary":
        result["boundary"] = "rebound_property"
    elif mutation == "group":
        next(r for r in right["results"] if r["name"] == "alternating_possessions")[
            "outcome"
        ]["value"]["possessions"][0].pop()
    elif mutation == "missing":
        right["results"].remove(result)
    else:
        result["name"] = "unexpected_case"
    assert compare_exceptions(left, right)["complete"] is False


def test_exception_comparator_rejects_duplicate_cases(compared):
    left, right = deepcopy(compared)
    right["results"].append(right["results"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        compare_exceptions(left, right)


def test_named_original_parser_exception_inventory_is_explicit():
    reference = prepare_reference()
    found = {}
    for path in (reference / "pbpstats").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "Exception"
                for base in node.bases
            ):
                found[node.name] = ".".join(
                    path.relative_to(reference).with_suffix("").parts
                )
    assert found == EXCEPTION_MODULES


def selected(name):
    return next(c for c in catalog() if c["name"] == name)


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "source",
        "unknown_file",
        "invalid_json",
        "not_bytes",
        "not_map",
        "period",
        "number",
        "boolean",
        "number_list",
    ],
)
def test_invalid_override_evidence_is_rejected(mutation):
    case = selected("bad_possession_override")
    raw, context = v3_inputs(case)
    files, source, bound = (
        override_bytes(case),
        "Reviewed correction",
        context.pbp_sha256,
    )
    if mutation == "hash":
        bound = "0" * 64
    elif mutation == "source":
        source = " "
    elif mutation == "unknown_file":
        files["unsupported_override.json"] = b"{}"
    elif mutation == "invalid_json":
        files[BAD] = b"{"
    elif mutation == "not_bytes":
        files[BAD] = "{}"
    else:
        bad = {
            "not_map": [],
            "period": {context.game_id: {"x": [2]}},
            "number": {context.game_id: {1: [0]}},
            "boolean": {context.game_id: {1: [True]}},
            "number_list": {context.game_id: {1: 2}},
        }[mutation]
        files[BAD] = json.dumps(bad).encode()
    with pytest.raises(V3DecodeError):
        StatsNbaV3PossessionLoader(
            raw, context, overrides=V3Overrides(files, source, bound)
        )


def test_override_inputs_are_auditable_and_detached_from_the_caller():
    case = selected("bad_possession_override")
    raw, context = v3_inputs(case)
    files = override_bytes(case)
    before = dict(files)
    loaded = StatsNbaV3PossessionLoader(
        raw,
        context,
        overrides=V3Overrides(files, "Reviewed correction", context.pbp_sha256),
    )
    assert files == before
    diagnostic = next(
        d for d in loaded.diagnostics if d["code"] == "recorded_override_input"
    )
    assert diagnostic["sha256"] == hashlib.sha256(files[BAD]).hexdigest()
    assert diagnostic["pbp_sha256"] == context.pbp_sha256
    files[BAD] = b"{}"
    assert loaded.bad_pbp_cases[context.game_id][1] == [2]
    assert loaded.capabilities["full_game_validated"] is False
    assert loaded.capabilities["possession_sequence_checked"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "source",
        "game",
        "missing",
        "duplicate",
        "period",
        "number",
        "invalid_json",
    ],
)
def test_invalid_provider_order_evidence_is_rejected(mutation):
    case = selected("recorded_provider_order_recovers_rebound")
    raw, context = v3_inputs(case)
    payload = provider_payload(case)
    source, bound = "Recorded independent order", context.pbp_sha256
    if mutation == "hash":
        bound = "0" * 64
    elif mutation == "source":
        source = ""
    elif mutation == "game":
        payload["g"]["gid"] = "0021900002"
    elif mutation == "missing":
        payload["g"]["pd"][0]["pla"].pop()
    elif mutation == "duplicate":
        payload["g"]["pd"][0]["pla"].append({"evt": 4})
    elif mutation == "period":
        payload["g"]["pd"][0]["p"] = 2
    elif mutation == "number":
        payload["g"]["pd"][0]["pla"][0]["evt"] = True
    evidence = b"{" if mutation == "invalid_json" else json.dumps(payload).encode()
    with pytest.raises(V3DecodeError):
        StatsNbaV3PossessionLoader(
            raw, context, event_order=V3EventOrder(evidence, source, bound)
        )


def test_provider_order_is_used_only_after_common_repairs_fail():
    case = selected("recorded_provider_order_recovers_rebound")
    raw, context = v3_inputs(case)
    with pytest.raises(
        V3DecodeError, match="additional recorded provider evidence"
    ) as error:
        StatsNbaV3PossessionLoader(raw, context)
    assert type(error.value.__context__).__name__ == "EventOrderError"
    evidence = json.dumps(provider_payload(case)).encode()
    loaded = StatsNbaV3PossessionLoader(
        raw,
        context,
        event_order=V3EventOrder(evidence, "Recorded order", context.pbp_sha256),
    )
    assert [e.event_num for e in loaded.events] == case["provider_order"]
    assert sum(d["code"] == "legacy_order_repair" for d in loaded.diagnostics) == 8
    assert sum(d["code"] == "recorded_provider_order" for d in loaded.diagnostics) == 1
    assert loaded.decoded.source_bytes == raw
    assert loaded.decoded.raw_rows == json.loads(raw)["game"]["actions"]


def test_unused_provider_order_does_not_reorder_valid_events():
    raw, context = v3_inputs(selected("alternating_possessions"))
    numbers = [row["actionNumber"] for row in json.loads(raw)["game"]["actions"]]
    evidence = json.dumps(
        provider_payload({"provider_order": list(reversed(numbers))})
    ).encode()
    loaded = StatsNbaV3PossessionLoader(
        raw,
        context,
        event_order=V3EventOrder(evidence, "Unused order", context.pbp_sha256),
    )
    assert [event.event_num for event in loaded.events] == numbers
    assert not any(d["code"] == "recorded_provider_order" for d in loaded.diagnostics)
