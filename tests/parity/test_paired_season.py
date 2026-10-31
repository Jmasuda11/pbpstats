"""Pinned 2024-25 V2/V3 export pairing: factual evidence, never adapter acceptance."""

import json
from collections import Counter
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
from tools.parity import v2_codes
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
# Decoder labels no V2 export row records, which load with no V2 code.
UNRECORDED = json.loads((ROOT / "tests/parity/unrecorded-labels.json").read_text())


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
        ("Made Shot", 1, v2_codes.SHOT_CODES),
        ("Missed Shot", 2, v2_codes.SHOT_CODES),
        ("Foul", 6, v2_codes.FOULS),
        ("Turnover", 5, v2_codes.TURNOVERS),
        ("Violation", 7, v2_codes.VIOLATIONS),
        ("Rebound", 4, v2_codes.REBOUNDS),
        ("Timeout", 9, v2_codes.TIMEOUTS),
        ("Jump Ball", 10, v2_codes.JUMP_BALLS),
        ("Instant Replay", 18, v2_codes.REPLAYS),
        ("Ejection", 11, v2_codes.EJECTIONS),
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


def test_the_decoder_accepts_exactly_the_labels_with_a_v2_code():
    # Each label the native classes decide from has the V2 code they are
    # checked against, but the one ejection label no V2 export records.
    for labels, codes in (
        (decoder.SHOTS, v2_codes.SHOT_CODES),
        (decoder.FOULS, v2_codes.FOULS),
        (decoder.TURNOVERS, v2_codes.TURNOVERS),
        (decoder.VIOLATIONS, v2_codes.VIOLATIONS),
        (decoder.REBOUNDS, v2_codes.REBOUNDS),
        (decoder.TIMEOUTS, v2_codes.TIMEOUTS),
        (decoder.WNBA_TIMEOUTS, v2_codes.WNBA_TIMEOUTS),
        (decoder.JUMP_BALLS, v2_codes.JUMP_BALLS),
        (decoder.REPLAYS, v2_codes.REPLAYS),
        (decoder.FREE_THROWS, v2_codes.FREE_THROWS),
        (decoder.FREE_THROWS, v2_codes.FLAGRANT_FREE_THROWS),
        (decoder.CLEAR_PATH_FREE_THROWS, v2_codes.CLEAR_PATH_FREE_THROWS),
        (decoder.TECHNICAL_FREE_THROWS, v2_codes.TECHNICAL_FREE_THROWS),
        (decoder.WNBA_CLEAR_PATH_FREE_THROWS, v2_codes.WNBA_CLEAR_PATH_FREE_THROWS),
    ):
        assert set(labels) == set(codes)
    unrecorded = {tuple(u["label"]) for u in UNRECORDED["unrecorded"]}
    assert unrecorded == {("Ejection", "Second Flagrant Type 1")}
    assert set(decoder.EJECTIONS) == set(v2_codes.EJECTIONS) | {"Second Flagrant Type 1"}


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
    # 0021500095 Q3 7:11: Fisher's second-technical ejection, as coach, one of
    # 36 in the 2015-16 V2 export, all 11/1, as 2026-27 game 0022600127's loads.
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
    # The native event decides from the V3 label, whose V2 code is pinned above.
    assert [event.action_type, event.sub_type] == observation["label"]


@pytest.mark.parametrize("unrecorded", UNRECORDED["unrecorded"], ids=lambda u: u["label"][1])
def test_a_label_no_v2_export_records_loads_with_no_code(unrecorded):
    # 0022600105 Q4 6:54: Sharpe's ejection for his second flagrant 1, a label
    # no V2 export from 2014-15 to 2016-17 or in 2024-25 records. The original
    # never reads an ejection's kind, so the native ejection needs no code.
    kind, subtype = unrecorded["label"]
    assert kind == "Ejection" and subtype in decoder.EJECTIONS
    assert subtype not in v2_codes.EJECTIONS and (kind, subtype) not in OTHER_SEASON_CODES
    named = {"Second Technical": 1, "First Flagrant Type 2": 3, "Other": 4}
    for export in unrecorded["v2_exports"]:
        codes = {row["code"]: row["label"] for row in export["ejection_codes"]}
        assert subtype not in codes.values()
        assert all(named.get(label, 0) == used for used, label in codes.items())
        if "path" in export:
            assert digest((ROOT / export["path"]).read_bytes()) == export["sha256"]
        else:
            assert "/datasets/" + export["member"].replace(".csv", ".tar.xz") in export["raw_url"]
    v2, _, _ = season()
    rows = Counter(int(r["EVENTMSGACTIONTYPE"]) for game in v2.values() for r in game
                   if r["EVENTMSGTYPE"] == "11")
    paired = next(e for e in unrecorded["v2_exports"] if e["season"] == "2024-25")
    assert rows == {row["code"]: row["rows"] for row in paired["ejection_codes"]}
    v3 = unrecorded["v3"]
    pbp = (ROOT / v3["path"]).read_bytes()
    assert digest(pbp) == v3["sha256"]
    action = json.loads(pbp)["game"]["actions"][v3["source_index"]]
    assert [action["actionType"], action["subType"]] == unrecorded["label"]
    loader = web.load_game(v3["game_id"], pbp, (ROOT / v3["boxscore_path"]).read_bytes(), "recorded")
    event = next(x for x in loader.events if x.event_num == action["actionNumber"])
    assert (event.action_type, event.sub_type) == (kind, subtype)
    assert not hasattr(event, "event_action_type")
    assert not any(d["code"] == "inferred_v2_code" for d in loader.diagnostics)


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
