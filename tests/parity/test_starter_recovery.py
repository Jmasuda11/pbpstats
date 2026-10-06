"""Evidence boundaries and full-loader recovery without global I/O patches."""

from copy import deepcopy
import hashlib
import json
import socket

import pytest

from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3StarterBoxscore,
    V3Overrides,
    V3DecodeError,
)
from pbpstats.resources.enhanced_pbp.start_of_period import (
    InvalidNumberOfStartersException,
)
from tools.parity.starter_cases import catalog, inputs, candidate, STARTERS, FILE
from tools.parity.scenarios import GAME, HOME, AWAY
from tools.parity.exception_cases import override_bytes


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Starter recovery tried to access the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def case_named(suffix):
    return next(
        case for case in catalog() if case["name"] == "starter_loader_" + suffix
    )


def evidence(case, raw, context):
    record = next(iter(case["responses"].values()))
    return dict(
        source_bytes=record["body"].encode(),
        source="Recorded boxscore fixture",
        pbp_sha256=context.pbp_sha256,
        request_params=deepcopy(record["params"]),
        status_code=record["status"],
        reason=record["reason"],
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "source",
        "bytes",
        "game",
        "keys",
        "bool_range",
        "status",
        "reason",
        "interval",
        "wrong_period",
    ],
)
def test_stale_or_wrong_request_evidence_cannot_supply_starters(mutation):
    case = case_named("boxscore_recovers_without_override")
    raw, context = inputs(case)
    fields, period = evidence(case, raw, context), 1
    if mutation == "hash":
        fields["pbp_sha256"] = "0" * 64
    elif mutation == "source":
        fields["source"] = " "
    elif mutation == "bytes":
        fields["source_bytes"] = "{}"
    elif mutation == "game":
        fields["request_params"]["GameId"] = "0021900002"
    elif mutation == "keys":
        fields["request_params"].pop("RangeType")
    elif mutation == "bool_range":
        fields["request_params"]["StartRange"] = False
    elif mutation == "status":
        fields["status_code"] = True
    elif mutation == "reason":
        fields["reason"] = None
    elif mutation == "interval":
        fields["request_params"]["EndRange"] += 1
    else:
        period = 2
    with pytest.raises(V3DecodeError):
        StatsNbaV3PossessionLoader(
            raw, context, starter_boxscores={period: V3StarterBoxscore(**fields)}
        )


def test_missing_recording_preserves_original_inference_failure_as_context():
    raw, context = inputs(case_named("boxscore_recovers_without_override"))
    with pytest.raises(
        V3DecodeError, match="recorded boxscore evidence for period 1"
    ) as error:
        StatsNbaV3PossessionLoader(raw, context)
    assert isinstance(error.value.__context__, InvalidNumberOfStartersException)
    assert "TeamId: {}".format(HOME) in str(error.value.__context__)
    assert context.period_starters == {}


def test_recovered_starters_are_auditable_without_changing_input_context():
    case = case_named("partial_override_falls_back")
    raw, context = inputs(case)
    before = deepcopy(context)
    fields = evidence(case, raw, context)
    loaded = StatsNbaV3PossessionLoader(
        raw,
        context,
        overrides=V3Overrides(
            override_bytes(case), "Reviewed correction", context.pbp_sha256
        ),
        starter_boxscores={1: V3StarterBoxscore(**fields)},
    )
    assert context == before
    assert loaded.decoded.context == before
    assert loaded.events[0].period_starters == STARTERS
    assert loaded.diagnostics[-1]["method"] == "boxscore"
    assert loaded.diagnostics[-1]["override_teams"] == [HOME]
    response = next(
        d for d in loaded.diagnostics if d["code"] == "recorded_starter_boxscore"
    )
    assert response["sha256"] == hashlib.sha256(fields["source_bytes"]).hexdigest()
    assert response["request_params"] == fields["request_params"]
    assert response["pbp_sha256"] == context.pbp_sha256
    assert loaded.capabilities["full_game_validated"] is False
    fields["request_params"]["EndRange"] = 999
    assert response["request_params"]["EndRange"] == 100


def test_substitution_validation_still_runs_after_starter_recovery():
    case = case_named("substitution_with_inferred_starters")
    substitution = next(e for e in case["events"] if e["kind"] == "sub")
    substitution["incoming"] = 3  # Already on court in independently supplied boxscore.
    with pytest.raises(V3DecodeError, match="Substitution contradicts current lineup"):
        candidate(case)


@pytest.mark.parametrize(
    "changes", [{HOME: [1, 2, 3, 4]}, {HOME: [1, 2, 3, 4, 4]}, {HOME: [1, 2, 3, 4, 11]}]
)
def test_invalid_explicit_starters_are_not_silently_replaced_by_recovery(changes):
    case = case_named("boxscore_recovers_without_override")
    raw, context = inputs(case)
    context.period_starters = {1: dict(STARTERS, **{})}
    context.period_starters[1].update(changes)
    with pytest.raises(V3DecodeError):
        StatsNbaV3PossessionLoader(
            raw,
            context,
            starter_boxscores={1: V3StarterBoxscore(**evidence(case, raw, context))},
        )


def test_partial_context_recovers_only_the_missing_period():
    case = case_named("period_2_interval")
    first = case_named("boxscore_recovers_without_override")["events"]
    case["events"] = first + case["events"]
    raw, context = inputs(case)
    context.period_starters = {1: deepcopy(STARTERS)}
    fields = evidence(case, raw, context)
    loaded = StatsNbaV3PossessionLoader(
        raw, context, starter_boxscores={2: V3StarterBoxscore(**fields)}
    )
    assert {
        e.period: e.period_starters for e in loaded.events if e.event_type == 12
    } == {1: STARTERS, 2: STARTERS}
    assert [
        d["period"] for d in loaded.diagnostics if d["code"] == "starter_recovery"
    ] == [2]


def test_original_dispatcher_and_event_methods_are_not_replaced():
    from pbpstats.resources.enhanced_pbp.stats_nba.start_of_period import (
        StatsStartOfPeriod,
    )

    original_method = StatsStartOfPeriod.get_period_starters
    loaded = candidate(case_named("boxscore_recovers_without_override"))
    assert type(loaded.events[0]) is StatsStartOfPeriod
    assert loaded.events[0].get_period_starters.__func__ is original_method
    assert "get_period_starters" not in loaded.events[0].__dict__


@pytest.mark.parametrize(
    "values", [{GAME: {1: []}}, {GAME: {1: {"bad": [1]}}}, {GAME: {1: {HOME: [False]}}}]
)
def test_malformed_starter_override_shape_is_rejected(values):
    raw, context = inputs(case_named("boxscore_recovers_without_override"))
    overrides = V3Overrides(
        {FILE: json.dumps(values).encode()}, "Correction fixture", context.pbp_sha256
    )
    with pytest.raises(V3DecodeError):
        StatsNbaV3PossessionLoader(raw, context, overrides=overrides)
