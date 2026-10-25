"""Pinned 2024-25 V2/V3 export pairing: factual evidence, never adapter acceptance."""

import json
from types import SimpleNamespace

import pytest

from pbpstats.data_loader.stats_nba_v3 import decoder, web
from tools.parity.paired_season import (
    EXPECTED,
    decoder_comparison,
    fidelity_witness,
    git_blob_sha1,
    manifest,
    pair,
    season,
)
from tools.parity.reference import ROOT, digest

# Decoder labels that neither paired season contains. They keep the original's
# own named codes and must never be mistaken for recorded evidence.
UNOBSERVED = {
    ("Foul", "Inbound"),
    ("Foul", "Personal Block"),
    ("Foul", "Shooting Block"),
}
# Decoder labels the paired seasons lack, coded from one pinned V2 export row of
# another season whose game and event number match a pinned V3 recording.
OTHER_SEASONS = json.loads((ROOT / "tests/parity/decoder-code-evidence.json").read_text())
OTHER_SEASON_CODES = {
    tuple(o["label"]): tuple(o["code"]) for o in OTHER_SEASONS["observations"]
}


@pytest.fixture(scope="module")
def facts():
    v2, v3, padding = season()
    result, _ = pair(v2, v3)
    result["export_padding"] = dict(sorted(padding.items()))
    result["fidelity_witness_matches"] = fidelity_witness()
    return result


def test_archives_are_the_pinned_upstream_blobs():
    evidence = manifest()
    for spec in evidence["archives"].values():
        raw = (ROOT / spec["path"]).read_bytes()
        assert len(raw) == spec["bytes"]
        assert digest(raw) == spec["sha256"]
        assert git_blob_sha1(raw) == spec["git_blob_sha1"]
        assert "/" + evidence["revision"] + "/" in spec["raw_url"]
    for path, expected in evidence["provenance_files"].items():
        assert digest((ROOT / path).read_bytes()) == expected


def test_facts_match_pinned_expectations(facts):
    assert facts == json.loads((ROOT / EXPECTED).read_bytes())


def test_exported_game_equals_its_separately_recorded_json(facts):
    assert facts["fidelity_witness_matches"] is True


def test_every_event_pairs_with_the_same_period_and_actor(facts):
    join = facts["join"]
    assert facts["games"] == facts["games_in_both"] == join["games_exact_event_set"]
    assert join["v2_only"] == join["v3_only"] == 0
    assert (
        join["v2_events"]
        == join["v3_primary"]
        == join["periods_equal"]
        == join["actors_equal"]
        == join["actor_teams_equal"]
    )
    assert all(row["identical"] for row in facts["v2_duplicate_rows"])
    roles = facts["secondary_roles"]
    assert roles["steals"] == roles["steal_matches_v2_player2"]
    assert roles["blocks"] == roles["block_matches_v2_player3"]


def test_each_v3_label_has_exactly_one_v2_code(facts):
    assert all(len(code["v2"]) == 1 for code in facts["codes"])


def test_v2_clock_is_the_floor_of_the_exact_v3_clock(facts):
    assert facts["clocks"]["other"] == 0


def test_order_differences_stay_within_one_instant(facts):
    assert facts["order"]["games_with_cross_instant_difference"] == 0


def test_candidate_decodes_every_observed_label_to_its_recorded_v2_code(facts):
    comparison = decoder_comparison(season()[1], facts)
    assert len(comparison) == len(facts["codes"])
    assert [c for c in comparison if c["decoder"]["verdict"] != "matches"] == []


def test_every_decoder_table_entry_is_recorded_or_declared_unobserved(facts):
    recorded = {
        (c["actionType"], c["subType"]): [
            (e["event_type"], e["action_type"]) for e in c["v2"]
        ]
        for c in facts["codes"]
    }
    tables = (
        ("Made Shot", 1, decoder.SHOT_CODES),
        ("Missed Shot", 2, decoder.SHOT_CODES),
        ("Foul", 6, decoder.FOULS),
        ("Turnover", 5, decoder.TURNOVERS),
        ("Violation", 7, decoder.VIOLATIONS),
        ("Rebound", 4, decoder.REBOUNDS),
        ("Timeout", 9, decoder.TIMEOUTS),
        ("Jump Ball", 10, decoder.JUMP_BALLS),
        ("Instant Replay", 18, decoder.REPLAYS),
        ("Ejection", 11, decoder.EJECTIONS),
    )
    for kind, event_type, table in tables:
        for subtype, code in table.items():
            if (kind, subtype) in UNOBSERVED:
                assert (kind, subtype) not in recorded
            elif (kind, subtype) in OTHER_SEASON_CODES:
                assert (kind, subtype) not in recorded
                assert OTHER_SEASON_CODES[kind, subtype] == (event_type, code), (kind, subtype)
            else:
                assert recorded[kind, subtype] == [(event_type, code)], (kind, subtype)


@pytest.mark.parametrize("observation", OTHER_SEASONS["observations"], ids=lambda o: o["label"][1])
def test_other_season_codes_match_their_pinned_v2_row_and_recording(observation):
    # 0022300678 Q1 11:23: Fox's swinging elbows turnover, the only one in the
    # 2023-24 V2 export, whose member hash is pinned with the archive's.
    # 0022000637 Q3 7:49: Barton's punching foul, the only one in the 2020-21 V2
    # export; the game went to overtime, so it loads with its period-5 box score.
    # 0021500087 Q3 1:51: Noel's flagrant 2 ejection, one of 13 in the 2015-16 V2
    # export, all 11/3; the decoder cannot load a 2015-16 game, so the code is
    # checked with the table, and 2026-27 game 0022600091 loads with it.
    # 0021500002 Q4 0:10: Cleveland's short timeout, one of 2,848 in the 2015-16
    # V2 export, all 9/2, as 2026-27 game 0022600103's loads.
    v2, v3 = observation["v2"], observation["v3"]
    assert "/datasets/" + v2["member"].replace(".csv", ".tar.xz") in v2["raw_url"]
    row = v2["row"]
    assert (int(row["EVENTMSGTYPE"]), int(row["EVENTMSGACTIONTYPE"])) == tuple(observation["code"])
    assert row["GAME_ID"] == v3["game_id"].lstrip("0")
    pbp = (ROOT / v3["path"]).read_bytes()
    assert digest(pbp) == v3["sha256"]
    action = json.loads(pbp)["game"]["actions"][v3["source_index"]]
    assert [action["actionType"], action["subType"]] == observation["label"]
    assert action["actionNumber"] == int(row["EVENTNUM"])
    assert action["personId"] == int(row["PLAYER1_ID"])
    if "unloadable" in v3:
        return
    box = (ROOT / v3["boxscore_path"]).read_bytes()
    periods = v3.get("period_boxscore_paths", {})

    def fetch(period, url, params):
        return SimpleNamespace(content=(ROOT / periods[str(period)]).read_bytes(), url=url,
                               status_code=200, reason="OK")

    loader = web.load_game(v3["game_id"], pbp, box, "recorded", fetch_boxscore=fetch)
    event = next(x for x in loader.events if x.event_num == action["actionNumber"])
    assert (event.event_type, event.event_action_type) == tuple(observation["code"])


def test_fouls_without_a_fouled_player_are_exactly_those_v2_never_names_one_for():
    v2, v3, _ = season()
    named, seen = set(), set()
    for game_id, rows in v2.items():
        fouled = {int(r["EVENTNUM"]): r["PLAYER2_ID"] not in ("", "0") for r in rows}
        for action in v3[game_id]:
            if action["actionType"] == "Foul":
                seen.add(action["subType"])
                if fouled[action["actionNumber"]]:
                    named.add(action["subType"])
    assert seen - named == decoder.FOULS_WITHOUT_FOULED_PLAYER
