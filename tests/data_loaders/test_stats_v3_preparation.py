"""Offline import, evidence review and publication against recorded full games."""

import hashlib
import json
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_stats_v3_lineups as synthetic
from v3_league_fixtures import DATA

from pbpstats.data_loader.stats_nba_v3.bundle import import_recordings
from pbpstats.data_loader.stats_nba_v3.game import V3GameLoadError, load_game
from pbpstats.data_loader.stats_nba_v3.lineups import V3LineupEvidence
from pbpstats.data_loader.stats_nba_v3.preparation import (
    _starters,
    _witnesses,
    prepare_game,
)

GAME = "1022600101"
GAMES = ["0021900001", "0022500341", "1022600100", GAME, "2022500001"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("preparation attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def directory(game_id):
    return Path(__file__).parents[1] / "data" if game_id == GAMES[0] else DATA / game_id


def reviewed(game_id):
    path = (
        "v3/lineups_0021900001.evidence.json"
        if game_id == GAMES[0]
        else "lineups.evidence.json"
    )
    return V3LineupEvidence.from_file(directory(game_id) / path)


def evidence(data):
    return V3LineupEvidence(json.dumps(data).encode(), "Explicit test review")


def prepare(game_id=GAME, base=None, **options):
    return prepare_game(
        game_id,
        base or directory(game_id),
        snapshot_complete=True,
        substitution_stream_source="Reviewed complete final fixture substitution stream",
        **options,
    )


def import_game(destination, game_id=GAME, **overrides):
    base = directory(game_id)
    box = base / f"game_details/stats_v3_boxscore_{game_id}.json"
    sidecar = json.loads(box.with_suffix(".evidence.json").read_bytes())
    options = dict(
        pbp_file=base / f"pbp/stats_v3_{game_id}.json",
        boxscore_file=box,
        pbp_source="Recorded official final PBP fixture; no new retrieval",
        boxscore_source=sidecar["source"],
        roster_complete=True,
        completeness_basis=sidecar["completeness_basis"],
        aliases=sidecar.get("aliases", []),
        bench_people=sidecar.get("bench_people", []),
        league_id=game_id[:2],
    )
    options.update(overrides)
    return import_recordings(game_id, destination, **options)


@pytest.mark.parametrize("game_id", GAMES)
def test_reviewed_full_games_prepare_and_load_unchanged(tmp_path, game_id):
    result = prepare(game_id, review=reviewed(game_id))
    assert result.ready, result.diagnostics
    output = tmp_path / "lineups.json"
    result.write_lineups(output)
    game = load_game(
        game_id, directory(game_id), snapshot_complete=True, lineup_evidence=output
    )
    original = load_game(
        game_id,
        directory(game_id),
        snapshot_complete=True,
        lineup_evidence=(
            "v3/lineups_0021900001.evidence.json" if game_id == GAMES[0] else None
        ),
    )
    assert game.possessions.base_stats == original.possessions.base_stats
    assert game.possessions.counts_by_team == original.possessions.counts_by_team
    assert result.review_template["batches"] == reviewed(game_id).data["batches"]


def test_import_review_publish_load_round_trip(tmp_path):
    bundle = import_game(tmp_path / "recorded game")
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    assert manifest["league_id"] == "10"
    assert "imported_at_utc" in manifest and "retrieved_at" not in manifest
    for entry in manifest["files"]:
        raw = (bundle / entry["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        if not entry["path"].endswith(".evidence.json"):
            assert raw == (DATA / GAME / entry["path"]).read_bytes()

    pending = prepare(base=bundle)
    assert not pending.ready
    assert {d.code for d in pending.diagnostics} == {"batch_review_required"}
    pending.write_report(bundle / "report.json")
    pending.write_review_template(bundle / "review.json")
    assert json.loads((bundle / "report.json").read_bytes())["ready"] is False
    with pytest.raises(ValueError, match="unresolved"):
        pending.write_lineups(bundle / "lineups.evidence.json")
    with pytest.raises(V3GameLoadError, match="source evidence"):
        prepare(base=bundle, review="review.json")  # Blank sources are not approvals.

    review = pending.review_template
    # Simulate a fresh review: each proposal matches an independently reviewed
    # batch in the checked-in fixture, whose raw PBP bytes were preserved above.
    accepted = {tuple(b["source_indices"]): b for b in reviewed(GAME).data["batches"]}
    for batch in review["batches"]:
        batch["source"] = accepted[tuple(batch["source_indices"])]["source"]
    (bundle / "review.json").write_text(json.dumps(review), encoding="utf-8")
    result = prepare(base=bundle, review="review.json")
    assert result.ready, result.diagnostics
    assert "review" in result.inputs
    result.write_lineups(bundle / "lineups.evidence.json")
    actual = load_game(GAME, bundle, snapshot_complete=True)
    expected = load_game(GAME, DATA / GAME, snapshot_complete=True)
    assert actual.possessions.base_stats == expected.possessions.base_stats
    with pytest.raises(FileExistsError):
        result.write_lineups(bundle / "lineups.evidence.json")


def test_quiet_overtime_player_requires_independent_starter_review():
    game_id = "2022500001"
    result = prepare(game_id)
    missing = [d for d in result.diagnostics if d.code == "missing_starters"]
    assert len(missing) == 1 and "period 5 away: 4" in missing[0].message
    period = result.review_template["periods"][0]
    assert period["period"] == 5 and 1631342 not in period["away"]
    assert len(result.review_template["resolved_replays"]) == 3
    assert not result.ready


def test_bench_technical_and_incoming_player_are_not_starter_witnesses():
    events = synthetic.events(
        [
            synthetic.start(),
            synthetic.row(
                "Foul",
                "Technical",
                "PT11M00S",
                8,
                synthetic.HOME,
                "Player8 T.FOUL (1 PF)",
            ),
            synthetic.sub(1, 6),
            synthetic.shot(6),
            synthetic.shot(2, "PT08M00S"),
            synthetic.end(),
        ]
    )
    found = _witnesses(events.items)
    assert set(found) == {1, 2}
    assert found[1]["source_index"] == 2  # The outgoing substitution is its witness.


def test_q1_positions_do_not_supply_later_period_starters():
    events = synthetic.events(
        [synthetic.start(), synthetic.end(), synthetic.start(2), synthetic.end(2)]
    )
    box = SimpleNamespace(
        source_sha256="test-box",
        source_data={
            "boxScoreTraditional": {
                side
                + "Team": {
                    "players": [
                        {"personId": pid, "position": "G" if offset < 5 else ""}
                        for offset, pid in enumerate(ids)
                    ]
                }
                for side, ids in [("home", range(1, 9)), ("away", range(11, 19))]
            }
        },
    )
    diagnostics = []
    periods, pending = _starters(
        events, box, {}, "Complete synthetic stream", diagnostics
    )
    assert periods[0]["home"] == [1, 2, 3, 4, 5]
    assert periods[1]["home"] == [] and periods[1]["away"] == []
    assert [p["period"] for p in pending] == [2]
    assert len(diagnostics) == 2


def test_incremental_review_keeps_prior_decisions():
    first = prepare()
    data = first.review_template
    batch = reviewed(GAME).data["batches"]
    proposed = data["batches"][0]["source_indices"]
    accepted = next(b for b in batch if b["source_indices"] == proposed)
    data["batches"] = [accepted]
    second = prepare(review=evidence(data))
    assert not second.ready
    assert accepted in second.review_template["batches"]
    assert proposed not in [list(d.source_indices) for d in second.diagnostics]
    assert len(second.review_template["batches"]) == len(
        first.review_template["batches"]
    )


@pytest.mark.parametrize("field", ["context_sha256", "snapshot_sha256"])
def test_stale_review_is_not_rebound(field):
    data = reviewed(GAME).data
    data[field] = "0" * 64
    with pytest.raises(V3GameLoadError, match="fingerprints") as caught:
        prepare(review=evidence(data))
    assert caught.value.diagnostic.stage == "preparation"


@pytest.mark.parametrize("case", ["duplicate_batch", "foreign_starter", "empty_source"])
def test_invalid_review_fails_explicitly(case):
    data = reviewed(GAME).data
    if case == "duplicate_batch":
        data["batches"].append(data["batches"][0])
    elif case == "foreign_starter":
        data["periods"][1]["home"][0] = data["periods"][1]["away"][0]
    else:
        data["batches"][0]["source"] = " "
    with pytest.raises(V3GameLoadError):
        prepare(review=evidence(data))


def test_changed_replay_resolution_is_validated_before_publication(tmp_path):
    game_id = "1022600100"
    data = reviewed(game_id).data
    data["resolved_replays"][0]["resolution"] = "assume_unchanged"
    result = prepare(game_id, review=evidence(data))
    assert not result.ready
    assert any(d.code == "validation_failed" for d in result.diagnostics)
    with pytest.raises(ValueError, match="unresolved"):
        result.write_lineups(tmp_path / "must-not-exist.json")
    assert not (tmp_path / "must-not-exist.json").exists()


@pytest.mark.parametrize(
    "change,code", [("wrong", "minutes_conflict"), ("missing", "missing_minutes")]
)
def test_published_minutes_must_reconcile(tmp_path, change, code):
    bundle = tmp_path / "game"
    shutil.copytree(DATA / GAME, bundle)
    path = bundle / f"game_details/stats_v3_boxscore_{GAME}.json"
    box = json.loads(path.read_bytes())
    players = box["boxScoreTraditional"]["homeTeam"]["players"]
    if change == "wrong":
        players[0]["statistics"]["minutes"] = "00:00"
    else:
        players[-1]["statistics"]["minutes"] = ""
        players[-1]["comment"] = ""  # A blank row is not evidence of zero minutes.
    path.write_text(json.dumps(box), encoding="utf-8")
    sidecar_path = path.with_suffix(".evidence.json")
    sidecar = json.loads(sidecar_path.read_bytes())
    sidecar["boxscore_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    # Explicit test review of unchanged PBP/lineups against the modified box score.
    review = reviewed(GAME).data
    candidate = prepare(base=bundle).lineup_candidate
    review.update({k: candidate[k] for k in ("context_sha256", "snapshot_sha256")})
    result = prepare(base=bundle, review=evidence(review))
    assert not result.ready and any(d.code == code for d in result.diagnostics)


def test_changed_input_cannot_be_published_and_results_are_defensive(tmp_path):
    bundle = tmp_path / "game"
    shutil.copytree(DATA / GAME, bundle)
    result = prepare(base=bundle, review="lineups.evidence.json")
    assert result.ready
    result.lineup_candidate["periods"].clear()
    assert result.lineup_candidate["periods"]
    with pytest.raises(AttributeError):
        result.diagnostics = ()
    with pytest.raises(TypeError):
        result.inputs["pbp"] = None
    path = bundle / "lineups.evidence.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="input changed"):
        result.write_lineups(bundle / "new-lineups.json")
    assert not (bundle / "new-lineups.json").exists()


def test_roster_and_substitution_completeness_require_separate_declarations(tmp_path):
    bundle = import_game(
        tmp_path / "partial", roster_complete=False, completeness_basis=""
    )
    with pytest.raises(V3GameLoadError, match="complete") as caught:
        prepare(base=bundle)
    assert caught.value.diagnostic.stage == "boxscore"
    with pytest.raises(V3GameLoadError, match="substitution_stream_source"):
        prepare_game(
            GAME, DATA / GAME, snapshot_complete=True, substitution_stream_source=""
        )
    with pytest.raises(V3GameLoadError) as caught:
        prepare_game(GAME, DATA / GAME, substitution_stream_source="Full substitutions")
    assert caught.value.diagnostic.stage == "configuration"


def test_import_adds_only_explicit_id_bound_aliases(tmp_path):
    path = DATA / GAME / f"pbp/stats_v3_{GAME}.json"
    raw = json.loads(path.read_bytes())
    rows = raw["game"]["actions"]
    row = next(r for r in rows if r.get("personId", 0) > 0 and r.get("teamId", 0) > 0)
    row["playerName"] = "Explicit Recorded Alias"
    modified = tmp_path / "pbp.json"
    modified.write_text(json.dumps(raw), encoding="utf-8")
    bundle = import_game(tmp_path / "bundle", pbp_file=modified)
    sidecar = json.loads(
        (bundle / f"game_details/stats_v3_boxscore_{GAME}.evidence.json").read_bytes()
    )
    alias = next(
        a for a in sidecar["aliases"] if "Explicit Recorded Alias" in a["names"]
    )
    assert alias["player_id"] == row["personId"] and alias["team_id"] == row["teamId"]
    assert hashlib.sha256(modified.read_bytes()).hexdigest() in alias["source"]
    assert "source row" in alias["source"]

    row["teamId"] = 123456789
    modified.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(V3GameLoadError, match="alias player/team conflicts"):
        import_game(tmp_path / "conflict", pbp_file=modified)
    assert not (tmp_path / "conflict").exists()

    row["personId"] = 987654321  # An unknown actor never becomes a roster member.
    modified.write_text(json.dumps(raw), encoding="utf-8")
    unknown = import_game(tmp_path / "unknown", pbp_file=modified)
    sidecar = json.loads(
        (unknown / f"game_details/stats_v3_boxscore_{GAME}.evidence.json").read_bytes()
    )
    assert all(a["player_id"] != row["personId"] for a in sidecar["aliases"])
    assert sidecar["bench_people"] == []


@pytest.mark.parametrize(
    "override",
    [
        {"league_id": "00"},
        {"pbp_source": ""},
        {"roster_complete": 1},
        {"completeness_basis": ""},
    ],
)
def test_bad_import_configuration_creates_nothing(tmp_path, override):
    target = tmp_path / "bundle"
    with pytest.raises(V3GameLoadError) as caught:
        import_game(target, **override)
    assert caught.value.diagnostic.stage == "import"
    assert not target.exists()


@pytest.mark.parametrize(
    "raw", [b'{"game":{},"game":{}}', b'{"value":NaN}', b"[" * 2000]
)
def test_bad_json_creates_nothing(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(V3GameLoadError):
        import_game(tmp_path / "bundle", pbp_file=path)
    assert not (tmp_path / "bundle").exists()


def test_import_never_overwrites_existing_directory(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.json"
    sentinel.write_bytes(b"unchanged")
    with pytest.raises(V3GameLoadError) as caught:
        import_game(target)
    assert isinstance(caught.value.__cause__, FileExistsError)
    assert (
        list(target.iterdir()) == [sentinel] and sentinel.read_bytes() == b"unchanged"
    )


def test_core_control_ambiguity_prevents_ready_result():
    game_id = "0022500165"
    result = prepare(game_id, review=reviewed(game_id))
    assert not result.ready
    assert any(d.stage == "validation" for d in result.diagnostics)
