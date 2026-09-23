"""Real response shape plus synthetic completeness/conflict evidence, offline."""

import hashlib
import json
import socket
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from pbpstats.data_loader.stats_nba_v3.boxscore import (
    StatsNbaV3BoxscoreFileLoader,
    StatsNbaV3BoxscoreLoader,
    V3BoxscoreSourceData,
)
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import StatsNbaV3PbpLoader
from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData

DATA = Path(__file__).resolve().parents[1] / "data"
GAME = "0022500165"
HOME, AWAY = 1610612761, 1610612749
PREFIX = f"game_details/stats_v3_boxscore_{GAME}"


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Box-score loading attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def payload():
    return json.loads((DATA / f"{PREFIX}.json").read_bytes())


def source(payload, **evidence_changes):
    """Synthetic declaration for exercising complete-roster paths, not a fixture claim."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    evidence = {
        "schema_version": 1,
        "game_id": GAME,
        "boxscore_sha256": hashlib.sha256(raw).hexdigest(),
        "source": "Synthetic test evidence based on recorded box-score shape",
        "scope": "full_game",
        "roster_complete": True,
        "completeness_basis": "Synthetic test declares both player arrays complete",
    }
    evidence.update(evidence_changes)
    return V3BoxscoreSourceData(
        raw, json.dumps(evidence).encode(), "test-boxscore.json", "test-evidence.json"
    )


def load(record):
    return StatsNbaV3BoxscoreLoader(GAME, SimpleNamespace(load_data=lambda _: record))


def participants(context, description, person=1630567, team=HOME, **extra):
    action = {
        "actionId": 1,
        "actionNumber": 1,
        "period": 1,
        "clock": "PT11M00S",
        "actionType": "Made Shot",
        "subType": "Jump Shot",
        "description": description,
        "personId": person,
        "teamId": team,
        "location": "h" if team == HOME else "v",
    }
    action.update(extra)
    raw = StatsNbaV3PbpLoader(
        GAME,
        SimpleNamespace(
            load_data=lambda _: V3PbpSourceData(
                {"game": {"gameId": GAME, "actions": [action]}}
            )
        ),
    )
    return StatsNbaV3ParticipantLoader(raw, context).items[0]


def test_published_fixture_integrity_and_context():
    manifest = json.loads((DATA / "v3/boxscore-manifest.json").read_bytes())
    listed = {f["path"] for f in manifest["fixtures"]}
    assert listed == {
        p.relative_to(DATA).as_posix()
        for p in DATA.glob("game_details/stats_v3_boxscore_*.json")
        if not p.name.endswith(".evidence.json")
    }
    for fixture in manifest["fixtures"]:
        raw = (DATA / fixture["path"]).read_bytes()
        evidence = (DATA / fixture["evidence_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == fixture["sha256"]
        assert hashlib.sha256(evidence).hexdigest() == fixture["evidence_sha256"]
        for prefix in ("observation", "lineup_evidence"):
            if prefix + "_path" in fixture:
                content = (DATA / fixture[prefix + "_path"]).read_bytes()
                assert (
                    hashlib.sha256(content).hexdigest() == fixture[prefix + "_sha256"]
                )
    loader = StatsNbaV3BoxscoreLoader(GAME, StatsNbaV3BoxscoreFileLoader(DATA))
    ctx = loader.context
    assert ctx.team_ids == (HOME, AWAY)
    assert len(ctx.players) == 29
    assert sum(p.team_id == HOME for p in ctx.players) == 14
    assert sum(p.team_id == AWAY for p in ctx.players) == 15
    assert ctx.player(202066).name == "Garrett Temple"  # Retain DNP players.
    assert ctx.player(203648).name == "Thanasis Antetokounmpo"
    assert ctx.player(1629018).aliases == (
        "Gary Trent Jr.",
        "Trent Jr.",
        "G. Trent Jr.",
    )
    assert ctx.candidates("Trent", AWAY) == ()
    assert ctx.candidates("Antetokounmpo", AWAY) == (203507, 203648)
    assert ctx.candidates("T. Antetokounmpo", AWAY) == (203648,)
    assert loader.source.boxscore_bytes == (DATA / f"{PREFIX}.json").read_bytes()
    fixture = next(f for f in manifest["fixtures"] if f["game_id"] == GAME)
    assert fixture["sha256"] in ctx.roster_source
    assert fixture["evidence_sha256"] in ctx.roster_source
    assert not ctx.roster_complete
    with pytest.raises(ValueError, match="complete roster evidence is missing"):
        loader.require_complete_roster()
    event = participants(ctx, "Barnes Jump Shot (2 PTS) (Ingram 1 AST)")
    assert event.require_player("actor") == 1630567
    assert event.participants["assister"].status == "unresolved"


def test_complete_context_integrates_with_participants_without_inventing_starters(
    payload,
):
    loader = load(source(payload))
    ctx = loader.require_complete_roster()
    assert ctx is loader.context
    assert (
        participants(ctx, "Barnes Jump Shot (2 PTS) (Ingram 1 AST)").require_player(
            "assister"
        )
        == 1627742
    )
    sub = participants(ctx, "SUB: Temple FOR Barnes", actionType="Substitution")
    assert sub.require_player("incoming") == 202066
    ambiguous = participants(
        ctx, "Trent Jr. Jump Shot (2 PTS) (Antetokounmpo 1 AST)", 1629018, AWAY
    )
    assert ambiguous.participants["assister"].status == "ambiguous"
    assert not hasattr(ctx, "period_starters")
    assert not hasattr(ctx, "lineups")
    # Position/statistics do not influence context or generate starter sets.
    for side in ("homeTeam", "awayTeam"):
        for player in payload["boxScoreTraditional"][side]["players"]:
            player["position"] = "G"
            player["statistics"] = {"minutes": "48:00"}
    changed = load(source(payload)).context
    assert changed.players == ctx.players
    assert changed.roster_complete


def test_alias_evidence_is_explicit_and_preserves_suffixes_and_accents(payload):
    row = payload["boxScoreTraditional"]["homeTeam"]["players"][0]
    row.update(firstName="Álex", familyName="Smith Jr.", nameI="Á. Smith Jr.")
    loader = load(
        source(
            payload,
            aliases=[
                {
                    "player_id": row["personId"],
                    "team_id": HOME,
                    "names": ["Smith", "A. Smith"],
                    "source": "Synthetic reviewed naming variant",
                }
            ],
        )
    )
    ctx = loader.context
    assert ctx.candidates("  á.  SMITH Jr.  ", HOME) == (row["personId"],)
    assert ctx.candidates("A. Smith", HOME) == (row["personId"],)
    assert ctx.candidates("Alex Smith Jr.", HOME) == (row["personId"],)
    assert ctx.candidates("Smith", AWAY) == ()
    assert (
        loader.evidence["aliases"][0]["source"] == "Synthetic reviewed naming variant"
    )
    without_extra = load(source(payload)).context
    assert without_extra.candidates("Smith", HOME) == ()
    assert without_extra.candidates("A. Smith", HOME) == ()


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("schema_version", True, "schema_version"),
        ("schema_version", 2, "schema_version"),
        ("game_id", "0021900001", "game_id"),
        ("boxscore_sha256", "0" * 64, "sha256"),
        ("source", " ", "source"),
        ("scope", "period", "scope"),
        ("scope", "partial", "full_game"),
        ("scope", "unknown", "full_game"),
        ("roster_complete", 1, "boolean"),
        ("roster_complete", None, "boolean"),
        ("completeness_basis", "", "completeness_basis"),
        ("aliases", {}, "aliases"),
    ],
)
def test_rejects_invalid_evidence(payload, field, value, match):
    with pytest.raises(ValueError, match=match) as error:
        load(source(payload, **{field: value}))
    assert GAME in str(error.value)
    assert "test-boxscore.json" in str(error.value)
    assert "test-evidence.json" in str(error.value)


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "game_id",
        "boxscore_sha256",
        "source",
        "scope",
        "roster_complete",
        "completeness_basis",
    ],
)
def test_rejects_missing_evidence_fields(payload, field):
    record = source(payload)
    evidence = json.loads(record.evidence_bytes)
    del evidence[field]
    with pytest.raises(ValueError, match=field):
        load(record._replace(evidence_bytes=json.dumps(evidence).encode()))


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda b: b.update(gameId="0021900001"), "gameId"),
        (lambda b: b.update(homeTeamId=True), "positive integer"),
        (lambda b: b.update(homeTeamId=AWAY), "distinct"),
        (lambda b: b["homeTeam"].update(teamId=AWAY), "conflicts"),
        (lambda b: b.update(awayTeam=None), "awayTeam"),
        (lambda b: b["homeTeam"].update(players={}), "array"),
        (lambda b: b["homeTeam"].update(players=[]), "at least five"),
        (
            lambda b: b["homeTeam"]["players"].append(b["awayTeam"]["players"][0]),
            "duplicate",
        ),
        (
            lambda b: b["homeTeam"]["players"][0].update(personId=HOME),
            "conflicting player ID",
        ),
        (lambda b: b["homeTeam"]["players"][0].update(personId=0), "positive integer"),
        (
            lambda b: b["homeTeam"]["players"][0].update(personId=True),
            "positive integer",
        ),
        (
            lambda b: b["homeTeam"]["players"][0].update(personId="1627742"),
            "positive integer",
        ),
        (lambda b: b["homeTeam"]["players"][0].update(teamId=AWAY), "containing team"),
        (lambda b: b["homeTeam"]["players"][0].update(firstName=""), "firstName"),
        (lambda b: b["homeTeam"]["players"][0].update(familyName=None), "familyName"),
        (lambda b: b["homeTeam"]["players"][0].update(nameI=123), "nameI"),
    ],
)
def test_rejects_conflicting_or_missing_boxscore_evidence(payload, change, match):
    change(payload["boxScoreTraditional"])
    with pytest.raises(ValueError, match=match):
        load(source(payload))


@pytest.mark.parametrize(
    "change",
    [
        {"player_id": 999},
        {"team_id": AWAY},
        {"source": ""},
        {"names": "Ingram"},
        {"names": []},
        {"names": [None]},
    ],
)
def test_rejects_unbound_or_invalid_aliases(payload, change):
    alias = {
        "player_id": 1627742,
        "team_id": HOME,
        "names": ["Ingram"],
        "source": "Synthetic",
    }
    alias.update(change)
    with pytest.raises(ValueError, match=r"evidence.aliases\[0\]"):
        load(source(payload, aliases=[alias]))


def test_context_rejects_conflicting_pbp_membership_and_team(payload):
    ctx = load(source(payload)).context
    with pytest.raises(ValueError, match="outside the complete roster"):
        participants(ctx, "Unknown Shot (2 PTS)", person=999)
    with pytest.raises(ValueError, match="disagree"):
        participants(ctx, "Barnes Shot (2 PTS)", team=AWAY)


def test_partial_roster_retains_known_players_but_never_resolves_unique_name(payload):
    payload["boxScoreTraditional"]["awayTeam"]["players"] = []
    loader = load(source(payload, scope="partial", roster_complete=False))
    assert loader.context.player(1630567).team_id == HOME
    assert not loader.context.roster_complete
    assert (
        participants(loader.context, "Barnes Shot (2 PTS) (Ingram 1 AST)")
        .participants["assister"]
        .status
        == "unresolved"
    )
    with pytest.raises(ValueError, match="complete roster evidence is missing"):
        loader.require_complete_roster()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b"\xff",
        b"{",
        b"[]",
        b"[" * 1100 + b"]" * 1100,
    ],
)
@pytest.mark.parametrize("field", ["boxscore_bytes", "evidence_bytes"])
def test_rejects_invalid_json_in_either_source(payload, raw, field):
    with pytest.raises(ValueError):
        load(source(payload)._replace(**{field: raw}))


def test_hash_binds_exact_bytes_even_when_decoded_json_matches(payload):
    record = source(payload)
    with pytest.raises(ValueError, match="sha256"):
        load(record._replace(boxscore_bytes=record.boxscore_bytes + b"\n"))


def test_missing_initial_alias_is_not_synthesized(payload):
    player = payload["boxScoreTraditional"]["homeTeam"]["players"][0]
    del player["nameI"]
    ctx = load(source(payload)).context
    assert ctx.player(player["personId"]).aliases == ("Brandon Ingram", "Ingram")
    assert ctx.candidates("B. Ingram", HOME) == ()


@pytest.mark.parametrize("field", ["boxscore_bytes", "evidence_bytes"])
def test_uninspectably_deep_unknown_fields_are_rejected_on_load(payload, field):
    raw = b'{"unknown":' + b'{"nested":' * 700 + b"0" + b"}" * 700 + b"}"
    with pytest.raises(ValueError, match="Stats V3 game"):
        load(source(payload)._replace(**{field: raw}))


def test_defensive_copies_and_no_mutation(payload):
    payload["futureField"] = {"nested": [1, 2]}
    record = source(payload)
    loader = load(record)
    loader.source_data["futureField"]["nested"].append(3)
    loader.evidence["source"] = "changed"
    assert loader.source_data == payload
    assert loader.evidence == json.loads(record.evidence_bytes)
    with pytest.raises(FrozenInstanceError):
        loader.context.players[0].name = "changed"
    assert loader.source.boxscore_bytes == record.boxscore_bytes


def test_file_loader_is_stateless_and_missing_files_are_explicit(tmp_path, payload):
    directory = tmp_path / "game_details"
    directory.mkdir()
    files = StatsNbaV3BoxscoreFileLoader(tmp_path)
    with pytest.raises(FileNotFoundError, match=GAME):
        StatsNbaV3BoxscoreLoader(GAME, files)
    record = source(payload)
    box_path = tmp_path / f"{PREFIX}.json"
    evidence_path = tmp_path / f"{PREFIX}.evidence.json"
    box_path.write_bytes(record.boxscore_bytes)
    with pytest.raises(FileNotFoundError, match="evidence"):
        StatsNbaV3BoxscoreLoader(GAME, files)
    evidence_path.write_bytes(record.evidence_bytes)
    before = {p: p.read_bytes() for p in directory.iterdir()}
    first = StatsNbaV3BoxscoreLoader(GAME, files)
    with pytest.raises(FileNotFoundError, match="0021900001"):
        StatsNbaV3BoxscoreLoader("0021900001", files)
    assert first.source.boxscore_bytes == record.boxscore_bytes
    assert {p: p.read_bytes() for p in directory.iterdir()} == before
    assert StatsNbaV3BoxscoreLoader(GAME, files).context == first.context
    other_game = "0021900001"
    payload["boxScoreTraditional"]["gameId"] = other_game
    other = source(payload, game_id=other_game)
    other_prefix = directory / f"stats_v3_boxscore_{other_game}"
    other_prefix.with_suffix(".json").write_bytes(other.boxscore_bytes)
    other_prefix.with_suffix(".evidence.json").write_bytes(other.evidence_bytes)
    second = StatsNbaV3BoxscoreLoader(other_game, files)
    assert second.context.game_id == other_game
    assert second.source.boxscore_bytes == other.boxscore_bytes
    assert first.source.boxscore_bytes == record.boxscore_bytes
    with pytest.raises(ValueError, match="10-digit"):
        files.load_data("../escape")


def test_source_contract_does_not_accept_unbound_payload(payload):
    with pytest.raises(TypeError, match="V3BoxscoreSourceData"):
        load(payload)
