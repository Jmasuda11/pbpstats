"""WNBA support: pinned 2025 V2/V3 export pairing, WNBA-only codes and the fetch tool."""

import json

import pytest
import responses

from pbpstats.data_loader.stats_nba_v3 import V3DecodeError, decoder, web
from pbpstats.data_loader.stats_nba_v3.decoder import DecodedV3, V3Context
from tools.parity.paired_season import (
    SEASONS,
    decoder_comparison,
    fidelity_witness,
    git_blob_sha1,
    manifest,
    pair,
    season,
)
from tools.parity.participant_names import roster_from_actors
from tools.parity.recorded import require
from tools.parity.reference import ROOT, digest
from tools.parity.team_heave_cases import catalog, load_v3, v3_inputs

WNBA = "wnba-2025"
RECORDINGS = json.loads((ROOT / "tests/parity/wnba-recordings.json").read_bytes())


@pytest.fixture(scope="module")
def facts():
    v2, v3, padding = season(WNBA)
    result, _ = pair(v2, v3)
    result["export_padding"] = dict(sorted(padding.items()))
    result["fidelity_witness_matches"] = fidelity_witness(WNBA)
    return result


def recording(name):
    return next(
        (ROOT / item["path"]).read_bytes()
        for item in RECORDINGS["files"]
        if item["path"].endswith("/" + name)
    )


def decoded_sample(label, game_id=None):
    """Decode the first exported event with this label, optionally under another ID."""
    source_game, actions, index = next(
        (game, actions, index)
        for game, actions in sorted(season(WNBA)[1].items())
        for index, action in enumerate(actions)
        if (action["actionType"], action["subType"]) == label
    )
    group = [a for a in actions if a["actionNumber"] == actions[index]["actionNumber"]]
    teams = tuple(sorted({a["teamId"] for a in actions if a["teamId"]}))
    game_id = game_id or source_game
    source = json.dumps({"game": {"gameId": game_id, "actions": group}}).encode()
    context = V3Context(
        game_id,
        teams,
        roster_from_actors(actions, teams, require),
        {},
        "WNBA 2025 export label sample",
        digest(source),
    )
    return DecodedV3(source, context)


def test_archives_and_recordings_are_pinned():
    evidence = manifest(WNBA)
    for spec in evidence["archives"].values():
        raw = (ROOT / spec["path"]).read_bytes()
        assert (len(raw), digest(raw), git_blob_sha1(raw)) == (
            spec["bytes"],
            spec["sha256"],
            spec["git_blob_sha1"],
        )
        assert "/" + evidence["revision"] + "/" in spec["raw_url"]
    for item in RECORDINGS["files"]:
        raw = (ROOT / item["path"]).read_bytes()
        assert (len(raw), digest(raw)) == (item["bytes"], item["sha256"])
    assert evidence["fidelity_witness"]["path"] in {i["path"] for i in RECORDINGS["files"]}


def test_facts_match_pinned_expectations(facts):
    assert facts == json.loads((ROOT / SEASONS[WNBA][1]).read_bytes())


def test_wnba_export_pairs_event_by_event_like_the_nba_export(facts):
    join = facts["join"]
    assert facts["games"] == facts["games_in_both"] == join["games_exact_event_set"] == 286
    assert join["v2_only"] == join["v3_only"] == 0
    assert (
        join["v2_events"]
        == join["v3_primary"]
        == join["periods_equal"]
        == join["actors_equal"]
        == join["actor_teams_equal"]
    )
    assert facts["fidelity_witness_matches"] is True
    assert all(len(code["v2"]) == 1 for code in facts["codes"])
    assert facts["clocks"]["other"] == 0
    assert facts["order"]["games_with_cross_instant_difference"] == 0


def test_candidate_decodes_every_wnba_label_to_its_recorded_v2_code(facts):
    comparison = decoder_comparison(season(WNBA)[1], facts)
    assert len(comparison) == len(facts["codes"])
    assert [c for c in comparison if c["decoder"]["verdict"] != "matches"] == []


def test_wnba_only_codes_are_recorded_for_wnba_and_never_for_nba(facts):
    wnba = {
        (c["actionType"], c["subType"]): [(e["event_type"], e["action_type"]) for e in c["v2"]]
        for c in facts["codes"]
    }
    nba = {
        (c["actionType"], c["subType"])
        for c in json.loads((ROOT / SEASONS["nba-2024"][1]).read_bytes())["codes"]
    }
    labels = [("Timeout", subtype, (9, code)) for subtype, code in decoder.WNBA_TIMEOUTS.items()]
    labels += [
        ("Free Throw", "Free Throw Clear Path {} of {}".format(*numbers), (3, code))
        for numbers, code in decoder.WNBA_CLEAR_PATH_FREE_THROWS.items()
    ]
    for kind, subtype, code in labels:
        assert wnba[kind, subtype] == [code]
        assert (kind, subtype) not in nba


@pytest.mark.parametrize(
    "label, code",
    [
        (("Timeout", "Official"), (9, 4)),
        (("Timeout", "Reset"), (9, 6)),
        (("Free Throw", "Free Throw Clear Path 1 of 1"), (3, 40)),
    ],
)
def test_wnba_only_codes_decode_for_wnba_games_alone(label, code):
    event = decoded_sample(label).projected[0]
    assert (event["EVENTMSGTYPE"], event["EVENTMSGACTIONTYPE"]) == code
    with pytest.raises(V3DecodeError):
        decoded_sample(label, game_id="0022500001")


def test_g_league_game_ids_stay_rejected():
    with pytest.raises(V3DecodeError, match="NBA and WNBA game IDs only"):
        decoded_sample(("Timeout", "Regular"), game_id="2022500001")


def test_team_heaves_stay_nba_facts():
    with pytest.raises(V3DecodeError, match="team-heave"):
        load_v3(v3_inputs(next(iter(catalog()))), game_id="1022500001")


def test_blank_subtype_fouls_keep_the_fouled_player_gap_in_wnba():
    # WNBA 2025 V2 names a fouled player for its one blank-subtype foul.
    v2, v3, _ = season(WNBA)
    named, seen = set(), set()
    for game_id, rows in v2.items():
        fouled = {int(r["EVENTNUM"]): r["PLAYER2_ID"] not in ("", "0") for r in rows}
        for action in v3[game_id]:
            if action["actionType"] == "Foul":
                seen.add(action["subType"])
                if fouled[action["actionNumber"]]:
                    named.add(action["subType"])
    assert seen - named <= decoder.FOULS_WITHOUT_FOULED_PLAYER - {""}
    assert "" in named
    assert decoded_sample(("Foul", "")).unknown_attribution[0]["role"] == "foul_drawn"


def test_wnba_starter_overrides_use_the_originals_integer_game_key(tmp_path):
    # IntDecoder keeps only leading-zero NBA game IDs as strings, so the original
    # looks other leagues' override games up by int(game_id). The adapter's
    # starter recovery follows the same rule.
    from types import SimpleNamespace

    from pbpstats.resources.enhanced_pbp.start_of_period import StartOfPeriod

    starters = [201886, 1642291, 1631009, 1628886, 1631044]
    (tmp_path / "overrides").mkdir()
    (tmp_path / "overrides/missing_period_starters.json").write_text(
        json.dumps({"1042600201": {"4": {"1611661330": starters}}}), encoding="utf-8"
    )
    found = {1611661330: starters[:4]}
    StartOfPeriod._check_both_teams_have_5_starters(
        SimpleNamespace(game_id="1042600201", league="wnba", period=4), found, str(tmp_path)
    )
    assert found == {1611661330: starters}


def test_league_hosts_follow_the_game_id():
    assert web.stats_url("0022500001") == "https://stats.nba.com/stats/"
    assert web.stats_url("1022500001") == "https://stats.wnba.com/stats/"


@responses.activate
def test_unsupported_leagues_fail_before_any_request():
    with pytest.raises(V3DecodeError, match="NBA and WNBA"):
        web.fetch_game("2022500001")
    assert len(responses.calls) == 0


def test_recorded_wnba_game_matches_the_original_on_v2():
    pbp = recording("stats_v3_1022500001.json")
    box = recording("stats_v3_boxscore_1022500001.json")
    data = json.loads(
        json.dumps(web.possessions_json(web.load_game("1022500001", pbp, box, "recorded")))
    )
    # The original's credits on the same game's V2 export (season differential).
    assert data["credited_possessions"] == {"1611661330": 76, "1611661322": 77}
    official = json.loads(box)["boxScoreTraditional"]
    assert data["final_score"] == {
        str(official[side]["teamId"]): official[side]["statistics"]["points"]
        for side in ("homeTeam", "awayTeam")
    }
    rows = json.loads(pbp)["game"]["actions"]
    indices = sorted(
        i for p in data["possessions"] for x in p["events"] for i in x["source_indices"]
    )
    assert indices == list(range(len(rows)))
    assert {p["start_clock"] for p in data["possessions"] if p["number"] == 1} == {"10:00"}
