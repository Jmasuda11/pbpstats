"""Lineups can remove name ambiguity only with independent complete starters."""

import json

import pytest

from pbpstats.data_loader.stats_nba_v3 import V3DecodeError
from tools.parity.participant_cases import catalog, load_v3, v3_inputs
from tools.parity.reference import ROOT, prepare_reference
from tools.parity.run import compare, worker
from tools.parity.scenarios import HOME, AWAY


CASES = list(catalog())


def test_complete_participant_facts_match_original_in_separate_workers():
    original = worker(prepare_reference(), suite="participants")
    candidate = worker(ROOT, provider="v3", suite="participants")
    result = compare(original, candidate)
    assert result["statuses"] == {"same": 3}, result
    assert result["matching_credit_cases"] == 3
    assert '"unavailable"' not in json.dumps(candidate["results"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_resolution_records_all_candidates_and_exact_on_court_evidence(case):
    rows, roster = v3_inputs(case)
    loaded = load_v3(rows, roster)
    (decision,) = loaded.decoded.participant_resolutions
    assert decision["candidates"] == case["namesakes"]
    assert decision["player_id"] == case["recipient"]
    jump = next(e for e in loaded.events if e.event_type == 10)
    # Original StatsEnhancedPbpItem exposes the recipient as player2_id and
    # opposing jumper as player3_id, swapping the constructor's V2 fields.
    assert jump.player2_id == case["recipient"]
    assert jump.player3_id == 11
    assert decision["on_court"] == sorted(
        jump.current_players[HOME] + jump.current_players[AWAY]
    )
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("namesakes", [[2, 12], [6, 16]])
def test_two_or_zero_matching_players_on_court_remain_ambiguous(namesakes):
    case = dict(CASES[0], namesakes=namesakes)
    rows, roster = v3_inputs(case)
    with pytest.raises(V3DecodeError, match="unresolved or ambiguous"):
        load_v3(rows, roster)


def test_period_change_resets_the_decoding_lineup():
    case = CASES[1]
    rows, roster = v3_inputs(case)
    from pbpstats.data_loader.stats_nba_v3 import V3Context
    from pbpstats.data_loader.stats_nba_v3.decoder import DecodedV3
    from tools.parity.reference import digest
    from tools.parity.scenarios import GAME

    # Player2 exits in Q1 but is explicitly a starter again in Q2. The decoder
    # must not reuse his Q1 bench status to pick the other Shared in Q2.
    jump = dict(
        next(r for r in rows if r["actionType"] == "Jump Ball"),
        actionNumber=99,
        actionId=99,
        period=2,
    )
    rows.append(jump)
    source = json.dumps(dict(game=dict(gameId=GAME, actions=rows))).encode()
    context = V3Context(
        GAME,
        (HOME, AWAY),
        roster,
        {p: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]} for p in (1, 2)},
        "Independent period starter assertions",
        digest(source),
    )
    with pytest.raises(V3DecodeError, match="source rows.*unresolved or ambiguous"):
        DecodedV3(source, context)


def test_invalid_substitution_cannot_create_disambiguating_bench_evidence():
    rows, roster = v3_inputs(CASES[1])
    sub = next(r for r in rows if r["actionType"] == "Substitution")
    sub.update(personId=7, description="SUB: Player6 FOR Player7")
    with pytest.raises(V3DecodeError, match="Substitution contradicts"):
        load_v3(rows, roster)


def test_resolution_is_rechecked_against_original_enhanced_lineups():
    rows, roster = v3_inputs(CASES[0])
    loaded = load_v3(rows, roster)
    loaded.decoded.participant_resolutions[0]["on_court"].remove(12)
    with pytest.raises(V3DecodeError, match="disagrees with original enhanced lineup"):
        loaded._validate_lineups()
