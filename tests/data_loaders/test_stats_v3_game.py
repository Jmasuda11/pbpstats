"""Public offline game loading, provenance, optional labels and stage failures."""

import hashlib
import json
import shutil
import socket
from pathlib import Path

import pytest
from v3_league_fixtures import DATA

from pbpstats.data_loader.stats_nba_v3.game import V3GameLoadError, load_game

OLD = Path(__file__).parents[1] / "data"
GAMES = ["0021900001", "0022500341", "1022600100", "1022600101", "2022500001"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("game loading attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.mark.parametrize("game_id", GAMES)
def test_one_call_loads_all_five_recorded_games(game_id):
    directory = OLD if game_id == GAMES[0] else DATA / game_id
    path = "v3/lineups_0021900001.evidence.json" if game_id == GAMES[0] else None
    loaded = load_game(
        game_id,
        directory,
        league_id=game_id[:2],
        lineup_evidence=path,
        snapshot_complete=True,
    )
    assert (len(loaded.possessions.events), len(loaded.possessions.items)) == {
        "0021900001": (573, 227),
        "0022500341": (494, 207),
        "1022600100": (433, 177),
        "1022600101": (400, 157),
        "2022500001": (510, 214),
    }[game_id]
    assert loaded.possessions.base_stats
    assert loaded.league_id == game_id[:2]
    assert loaded.capabilities["base_stats"] == "complete"
    assert loaded.capabilities["detailed_event_stats"] == "unavailable"
    assert len(loaded.possession_start_types) == len(loaded.possessions.items)
    assert (None in loaded.possession_start_types) == (game_id[:2] == "10")
    with pytest.raises(ValueError, match="detailed V3 event statistics"):
        loaded.possessions.events[0].event_stats
    for source in loaded.inputs.values():
        assert (
            hashlib.sha256(Path(source.path).read_bytes()).hexdigest() == source.sha256
        )
    with pytest.raises(TypeError):
        loaded.capabilities["base_stats"] = "unavailable"


@pytest.mark.parametrize(
    "game_id,partial", [("1022600100", True), ("2022500001", False)]
)
def test_optional_zone_conflicts_do_not_erase_core_results(game_id, partial):
    game = load_game(
        game_id,
        DATA / game_id,
        snapshot_complete=True,
        shot_evidence=(DATA.parent / "shot_zones" / f"{game_id}-live.json").resolve(),
    )
    assert game.capabilities["shot_zone_evidence"] == (
        "partial" if partial else "complete"
    )
    assert (None in game.possession_start_types) == partial
    assert any(d.stage == "shot_zones" for d in game.diagnostics) == partial
    for index, value in enumerate(game.possession_start_types):
        if value is None:
            assert any(d.possession_index == index for d in game.diagnostics)
            with pytest.raises(ValueError, match="shot zones"):
                game.possessions.items[index].possession_start_type


def test_relocating_bundle_preserves_fingerprints_and_records_actual_paths(tmp_path):
    game_id = "1022600101"
    target = tmp_path / "copied game"
    shutil.copytree(DATA / game_id, target)
    before = {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    original = load_game(game_id, DATA / game_id, snapshot_complete=True)
    moved = load_game(game_id, target, snapshot_complete=True)
    assert original.boxscore.context == moved.boxscore.context
    assert original.lineups.evidence.data == moved.lineups.evidence.data
    assert moved.possessions.base_stats == original.possessions.base_stats
    assert all(target in Path(i.path).parents for i in moved.inputs.values())
    assert before == {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"snapshot_complete": False},
        {"snapshot_complete": 1},
        {"snapshot_complete": True, "league_id": "00"},
    ],
)
def test_configuration_requires_explicit_completeness_and_matching_league(
    tmp_path, options
):
    with pytest.raises(V3GameLoadError) as caught:
        load_game("1022600101", tmp_path / "absent", **options)
    assert caught.value.diagnostic.stage == "configuration"


@pytest.mark.parametrize(
    "file,stage",
    [
        ("game_details/stats_v3_boxscore_1022600101.json", "boxscore"),
        ("pbp/stats_v3_1022600101.json", "pbp"),
        ("lineups.evidence.json", "lineups"),
    ],
)
def test_missing_required_file_has_stage_and_original_cause(tmp_path, file, stage):
    target = tmp_path / "game"
    shutil.copytree(DATA / "1022600101", target)
    (target / file).unlink()
    with pytest.raises(V3GameLoadError) as caught:
        load_game("1022600101", target, snapshot_complete=True)
    assert caught.value.game_id == "1022600101"
    assert caught.value.diagnostic.stage == stage
    assert caught.value.diagnostic.code == "missing_file"
    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_supplied_bad_optional_file_is_an_explicit_input_error(tmp_path):
    with pytest.raises(V3GameLoadError) as caught:
        load_game(
            "1022600101",
            DATA / "1022600101",
            snapshot_complete=True,
            shot_evidence=tmp_path / "missing.json",
        )
    assert caught.value.diagnostic.stage == "shot_zones"


def test_stale_lineup_evidence_is_not_silently_rebound(tmp_path):
    target = tmp_path / "game"
    shutil.copytree(DATA / "1022600101", target)
    path = target / "lineups.evidence.json"
    evidence = json.loads(path.read_bytes())
    evidence["snapshot_sha256"] = "0" * 64
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(V3GameLoadError, match="snapshot_sha256") as caught:
        load_game("1022600101", target, snapshot_complete=True)
    assert caught.value.diagnostic.stage == "lineups"


def test_complete_declaration_cannot_turn_one_period_into_a_full_game(tmp_path):
    target = tmp_path / "game"
    shutil.copytree(DATA / "1022600101", target)
    path = target / "pbp/stats_v3_1022600101.json"
    raw = json.loads(path.read_bytes())
    raw["game"]["actions"] = [r for r in raw["game"]["actions"] if r["period"] == 1]
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(V3GameLoadError, match="four regulation periods"):
        load_game("1022600101", target, snapshot_complete=True)


@pytest.mark.parametrize(
    "game_id,stage", [("0022500165", "possessions"), ("0022500166", "participants")]
)
def test_recorded_rejections_report_the_failing_stage(game_id, stage):
    with pytest.raises(V3GameLoadError) as caught:
        load_game(game_id, DATA / game_id, snapshot_complete=True)
    assert caught.value.diagnostic.stage == stage
