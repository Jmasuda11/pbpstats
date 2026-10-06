"""Explicit team-heave extension; original decision and rejection gates remain."""

from copy import deepcopy
import json

import pytest

from pbpstats.data_loader.stats_nba_v3 import V3DecodeError
from pbpstats.data_loader.stats_nba_v3.team_heave import TEAM_HEAVE_VERSION, V3TeamHeave
from tools.parity.reference import ROOT, digest, prepare_reference
from tools.parity.run import worker
from tools.parity.snapshot import first_difference
from tools.parity.team_heave_cases import catalog, load_v3, v3_inputs
from tools.parity.scenarios import HOME


CASES = list(catalog())
EVIDENCE = json.loads((ROOT / "tests/parity/team-heave-evidence.json").read_bytes())


@pytest.fixture(scope="module")
def results():
    return worker(prepare_reference(), suite="team-heaves"), worker(
        ROOT, provider="v3", suite="team-heaves"
    )


@pytest.mark.parametrize("index", range(len(CASES)), ids=[c["name"] for c in CASES])
def test_shared_behavior_matches_original_team_miss_analogue(results, index):
    old, new = (r["results"][index] for r in results)
    assert old["status"] == new["status"] == "ok", (old, new)
    assert old["credits"] == new["credits"]
    assert first_difference(old["snapshot"], new["snapshot"]) is None
    assert '"unavailable"' not in json.dumps(new["snapshot"])


@pytest.mark.parametrize("blocked", [False, True])
def test_team_statistics_do_not_debit_any_shooter_and_keep_blocker_credit(blocked):
    case = next(c for c in CASES if c["blocked"] == blocked and c["substitute"])
    rows = v3_inputs(case)
    original = deepcopy(rows)
    loaded = load_v3(rows)
    heave = next(e for e in loaded.events if isinstance(e, V3TeamHeave))
    assert heave.player1_id == 0 and heave.team_id == HOME
    assert heave.event_action_type is None
    assert heave.distance is None and heave.locX is None and heave.locY is None
    assert heave.shot_data["Attribution"] == "team"
    assert heave.shot_data["IsTeamHeave"]
    assert heave.is_heave and not heave.is_corner_3
    shooting = [s for s in heave.event_stats if s["team_id"] == HOME and
                ("Arc3" in s["stat_key"] or "Heave" in s["stat_key"])]
    assert shooting and all(s["player_id"] == 0 for s in shooting)
    assert any(s["stat_key"] == "HeaveMisses" for s in shooting)
    assert any(s["stat_key"] == "BlockedArc3" and s["player_id"] == 11
               for s in heave.event_stats) == blocked
    assert loaded.decoded.raw_rows == rows == original
    assert sorted(i for e in loaded.events for i in e.v3_source_indices) == list(range(len(rows)))
    assert loaded.capabilities["extensions"] == [TEAM_HEAVE_VERSION]
    assert loaded.capabilities["source_order_checked"]
    assert loaded.capabilities["possession_sequence_checked"]
    assert not loaded.capabilities["full_game_validated"]
    with pytest.raises(V3DecodeError, match="attribution completeness"):
        loaded.event_stats


@pytest.mark.parametrize("change", [
    {"personId": 1}, {"shotValue": 3}, {"shotResult": "Made"},
    {"isFieldGoal": 1}, {"xLegacy": 400}, {"playerName": "Player1"},
    {"location": ""}, {"location": "x"}, {"teamId": 1610612740},
    {"subType": "Other"},
])
def test_conflicting_or_insufficient_heave_facts_reject(change):
    rows = v3_inputs(CASES[0])
    next(r for r in rows if r["actionType"] == "Heave").update(change)
    with pytest.raises(V3DecodeError, match="heave|Heave"):
        load_v3(rows)


def test_conflicting_home_away_witnesses_reject():
    rows = v3_inputs(CASES[0])
    next(r for r in rows if r["actionType"] == "Made Shot")["location"] = "v"
    with pytest.raises(V3DecodeError, match="team evidence"):
        load_v3(rows)


@pytest.mark.parametrize("change", [
    {"description": "Unknown BLOCK (1 BLK)"},
    {"description": "Player1 BLOCK (1 BLK)"},
    {"location": "h"}, {"teamId": HOME},
])
def test_name_only_heave_blocker_requires_opposing_roster_evidence(change):
    rows = v3_inputs(next(c for c in CASES if c["blocked"]))
    next(r for r in rows if "BLOCK" in r["description"]).update(change)
    with pytest.raises(V3DecodeError, match="Participant|blocker location|participant and team|team evidence"):
        load_v3(rows)


def test_explicit_blocker_identity_is_retained():
    rows = v3_inputs(next(c for c in CASES if c["blocked"]))
    next(r for r in rows if "BLOCK" in r["description"])["personId"] = 11
    heave = next(e for e in load_v3(rows).events if isinstance(e, V3TeamHeave))
    assert heave.player3_id == 11


@pytest.mark.parametrize("observation", EVIDENCE["observations"], ids=lambda o: o["game_id"])
def test_recorded_heave_evidence_is_byte_pinned(observation):
    raw = (ROOT / observation["path"]).read_bytes()
    assert digest(raw) == observation["sha256"]
    game = json.loads(raw)["game"]
    assert game["gameId"] == observation["game_id"]
    row = game["actions"][observation["source_index"]]
    assert row == observation["row"]
    assert row["actionType"] == "Heave" and row["subType"] == "Team Field Goal Attempt"
    assert row["personId"] == row["teamId"] == row["shotValue"] == 0


def test_original_order_repair_reconstructs_extension_before_linking():
    rows = v3_inputs(next(c for c in CASES if c["substitute"] and not c["blocked"]))
    shot = next(i for i, r in enumerate(rows) if r["actionType"] == "Heave")
    rows[shot - 1]["clock"] = rows[shot]["clock"]
    rows[shot - 1], rows[shot] = rows[shot], rows[shot - 1]
    loaded = load_v3(rows)
    heave = next(e for e in loaded.events if isinstance(e, V3TeamHeave))
    assert heave.next_event.missed_shot is heave
    assert heave.next_event.is_real_rebound is False
    assert any(d["code"] == "legacy_order_repair" for d in loaded.diagnostics)
