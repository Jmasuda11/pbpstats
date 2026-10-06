"""Independent recorded-context evidence and complete-corpus accounting gates."""

import json
import socket

import pytest

from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader
from tools.parity.corpus import audit_game, audit_inventory, main
from tools.parity.recorded import (
    EvidenceError,
    prepare_recorded,
    read_capture,
    reconcile,
)
from tools.parity.reference import ROOT, digest


GAME, HOME, AWAY = "0022500001", 1610612761, 1610612740
PBP = "bundle/pbp/stats_v3_{}.json".format(GAME)
BOX = "bundle/game_details/stats_v3_boxscore_{}.json".format(GAME)
EVIDENCE = BOX.replace(".json", ".evidence.json")


def encode(value):
    return json.dumps(value, ensure_ascii=True).encode()


def recording():
    rows = []

    def row(period, clock, kind, subtype="", team=0, player=0, description=""):
        number = len(rows) + 1
        rows.append(
            dict(
                actionId=number,
                actionNumber=number,
                period=period,
                clock="PT{}M{:02d}S".format(*divmod(clock, 60)),
                actionType=kind,
                subType=subtype,
                teamId=team,
                personId=player,
                description=description,
                playerName="Player{}".format(player) if player else "",
                isFieldGoal=int(kind == "Made Shot"),
                shotValue=2 if kind == "Made Shot" else 0,
                shotResult="Made" if kind == "Made Shot" else "",
                xLegacy=0,
                yLegacy=100,
            )
        )

    for period in range(1, 5):
        row(period, 720, "period", "start")
        for index in range(5):
            for offset, team, player in ((0, HOME, 1 + index), (1, AWAY, 11 + index)):
                row(
                    period,
                    700 - index * 20 - offset * 10,
                    "Made Shot",
                    "Jump Shot",
                    team,
                    player,
                    "Player{} Jump Shot".format(player),
                )
        if period == 1:
            row(
                period,
                360,
                "Substitution",
                team=HOME,
                player=1,
                description="SUB: Player6 FOR Player1",
            )
            row(period, 350, "Made Shot", "Jump Shot", HOME, 6, "Player6 Jump Shot")
            row(period, 340, "Made Shot", "Jump Shot", AWAY, 11, "Player11 Jump Shot")
        row(period, 0, "period", "end")
    box = {"gameId": GAME, "homeTeamId": HOME, "awayTeamId": AWAY}
    for side, team, start in (("homeTeam", HOME, 1), ("awayTeam", AWAY, 11)):
        box[side] = {
            "teamId": team,
            "statistics": {"points": 42},
            "players": [
                {
                    "personId": player,
                    "familyName": "Player{}".format(player),
                    "firstName": "Test",
                    "position": "G" if player < start + 5 else "",
                    "statistics": {
                        "minutes": (
                            "42:00"
                            if player == 1
                            else (
                                "6:00"
                                if player == 6
                                else "48:00" if player < start + 5 else ""
                            )
                        )
                    },
                }
                for player in range(start, start + 6)
            ],
        }
    files = {
        PBP: encode({"game": {"gameId": GAME, "actions": rows}}),
        BOX: encode({"boxScoreTraditional": box}),
    }
    files[EVIDENCE] = encode(
        {
            "schema_version": 1,
            "game_id": GAME,
            "scope": "full_game",
            "boxscore_sha256": digest(files[BOX]),
            "roster_complete": True,
            "source": "Independent synthetic full-game recording",
        }
    )
    return files


def change_rows(files, change):
    payload = json.loads(files[PBP])
    change(payload["game"]["actions"])
    files[PBP] = encode(payload)


def capture(tmp_path, files=None):
    files = recording() if files is None else files
    manifest = {}
    for relative, data in files.items():
        path = tmp_path / "capture" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest[relative] = {
            "sha256": digest(data),
            "previous_sha256": digest(data),
            "unchanged": True,
        }
    return {
        "game_id": GAME,
        "capture": "capture",
        "previous_status": "validated",
        "files": manifest,
    }


def inventory(tmp_path, game):
    previous = {
        "games": [
            {
                "game_id": GAME,
                "capture": str(tmp_path / "capture"),
                "status": "validated",
                "source_hashes": {p: f["sha256"] for p, f in game["files"].items()},
            }
        ]
    }
    previous_path = tmp_path / "previous.json"
    previous_path.write_bytes(encode(previous))
    path = tmp_path / "inventory.json"
    path.write_bytes(
        encode(
            {
                "ingestion_root": str(tmp_path),
                "games": [game],
                "previous_report": {
                    "path": previous_path.name,
                    "sha256": digest(previous_path.read_bytes()),
                },
            }
        )
    )
    return path


def test_independent_starters_and_individual_minutes():
    files = recording()
    prepared = prepare_recorded(GAME, files)
    assert prepared.context.period_starters == {
        p: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]} for p in range(1, 5)
    }
    loaded = StatsNbaV3PossessionLoader(prepared.source, prepared.context)
    result = reconcile(loaded, prepared)
    minutes = {r["player_id"]: r for r in result["player_minutes"]}
    assert minutes[1]["raw_seconds"] == "2520"
    assert minutes[6]["raw_seconds"] == "360"
    assert result["score"] == {HOME: 42, AWAY: 42}
    assert files == recording()


def test_raw_hashes_bound_to_context_and_saved_starters_rechecked():
    files = recording()
    saved = {
        "schema_version": 1,
        "game_id": GAME,
        "context_sha256": "untrusted prior parser fingerprint",
        "periods": [
            {"period": p, "home": [1, 2, 3, 4, 5], "away": [11, 12, 13, 14, 15]}
            for p in range(1, 5)
        ],
    }
    path = "bundle/lineups.evidence.json"
    files[path] = encode(saved)
    prepared = prepare_recorded(GAME, files)
    assert prepared.provenance["saved_starters_checked"] == [path]
    assert prepared.provenance["prior_parser_outputs_used"] is False
    assert prepared.context.pbp_sha256 == digest(files[PBP])
    saved["periods"][1]["home"][0] = 6
    files[path] = encode(saved)
    with pytest.raises(EvidenceError, match="Saved starters disagree"):
        prepare_recorded(GAME, files)


def test_old_ready_flags_cannot_supply_missing_starter_evidence():
    files = recording()
    change_rows(
        files,
        lambda rows: rows.__setitem__(
            slice(None),
            [r for r in rows if not (r["period"] == 2 and r["personId"] == 5)],
        ),
    )
    files["bundle/preparation-report.json"] = encode(
        {
            "ready": True,
            "lineup_candidate": {"periods": [{"period": 2, "home": [1, 2, 3, 4, 5]}]},
        }
    )
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, files)
    assert error.value.code == "starter_evidence"


def test_accent_aliases_are_id_bound_and_collisions_stay_ambiguous():
    files = recording()
    box = json.loads(files[BOX])
    box["boxScoreTraditional"]["homeTeam"]["players"][5]["familyName"] = "Pláyer6"
    files[BOX] = encode(box)
    evidence = json.loads(files[EVIDENCE])
    evidence["boxscore_sha256"] = digest(files[BOX])
    files[EVIDENCE] = encode(evidence)
    change_rows(
        files,
        lambda rows: [
            r.update(playerName="Pláyer6") for r in rows if r["personId"] == 6
        ],
    )
    prepared = prepare_recorded(GAME, files)
    assert "Player6" in prepared.context.roster[6]["names"]
    change_rows(files, lambda rows: rows[3].update(playerName="Player6"))
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, files)
    assert error.value.code == "participant_evidence"


def test_later_actor_alias_can_resolve_earlier_incoming_substitution():
    files = recording()

    def change(rows):
        rows[11]["description"] = "SUB: Hansen FOR Player1"
        rows[12].update(
            actionType="Rebound",
            subType="Unknown",
            description="Hansen REBOUND (Off:0 Def:1)",
        )

    change_rows(files, change)
    before = dict(files)
    prepared = prepare_recorded(GAME, files)
    assert prepared.substitutions[11] == (HOME, 1, 6)
    assert "Hansen" in prepared.context.roster[6]["names"]
    assert prepared.provenance["actor_alias_witnesses"] == [
        dict(
            source_index=12,
            action_number=13,
            player_id=6,
            team_id=HOME,
            name="Hansen",
            role="rebounder",
        )
    ]
    assert files == before


def test_an_incoming_description_alone_cannot_establish_an_alias():
    files = recording()
    change_rows(
        files, lambda rows: rows[11].update(description="SUB: Hansen FOR Player1")
    )
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, files)
    assert error.value.code == "participant_evidence"


def test_unwitnessed_given_name_does_not_create_a_description_alias():
    files = recording()
    box = json.loads(files[BOX])
    players = box["boxScoreTraditional"]["homeTeam"]["players"]
    players[5]["firstName"] = "Hansen"
    files[BOX] = encode(box)
    evidence = json.loads(files[EVIDENCE])
    evidence["boxscore_sha256"] = digest(files[BOX])
    files[EVIDENCE] = encode(evidence)
    change_rows(
        files, lambda rows: rows[11].update(description="SUB: Hansen FOR Player1")
    )
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, files)
    assert error.value.code == "participant_evidence"


def shared_tip_recording(namesakes=(6, 12), period=1):
    files = recording()
    box = json.loads(files[BOX])
    for side in ("homeTeam", "awayTeam"):
        for player in box["boxScoreTraditional"][side]["players"]:
            if player["personId"] in namesakes:
                player["nameI"] = "Shared"
    files[BOX] = encode(box)
    evidence = json.loads(files[EVIDENCE])
    evidence["boxscore_sha256"] = digest(files[BOX])
    files[EVIDENCE] = encode(evidence)

    def change(rows):
        target = next(r for r in rows if r["period"] == period and r["personId"] == 1)
        target.update(
            actionType="Jump Ball",
            subType="",
            description="Jump Ball Player1 vs. Player11: Tip to Shared",
        )

    change_rows(files, change)
    return files


def test_independent_lineup_resolves_only_one_on_court_namesake():
    prepared = prepare_recorded(GAME, shared_tip_recording())
    (decision,) = prepared.provenance["participant_resolutions"]
    assert decision["source_index"] == 1
    assert decision["candidates"] == [6, 12]
    assert decision["player_id"] == 12
    assert decision["on_court"] == [1, 2, 3, 4, 5, 11, 12, 13, 14, 15]
    loaded = StatsNbaV3PossessionLoader(
        prepared.source, prepared.context, validate_possessions=False
    )
    assert loaded.decoded.participant_resolutions[0]["player_id"] == 12


@pytest.mark.parametrize("namesakes", [(2, 12), (6, 16)])
def test_ambiguous_or_absent_on_court_recipient_stays_blocked(namesakes):
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, shared_tip_recording(namesakes))
    assert error.value.code == "participant_evidence"
    assert len(error.value.details["on_court_candidates"]) != 1


def test_tip_cannot_supply_the_starters_used_to_disambiguate_it():
    files = shared_tip_recording((5, 16), period=2)
    change_rows(
        files,
        lambda rows: rows.__setitem__(
            slice(None),
            [r for r in rows if not (r["period"] == 2 and r["personId"] == 5)],
        ),
    )
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, files)
    assert error.value.code == "starter_evidence"
    assert error.value.details["players"] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda rows: rows.pop(), "period_completeness"),
        (lambda rows: rows[2].update(clock="PT12M01S"), "clock_order"),
        (lambda rows: rows[1].update(teamId=AWAY), "roster_identity"),
        (
            lambda rows: rows[11].update(description="SUB: Player6 FOR Player2"),
            "substitution_evidence",
        ),
    ],
)
def test_contradictory_raw_context_is_rejected(mutation, code):
    files = recording()
    change_rows(files, mutation)
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, files)
    assert error.value.code == code


def test_tampered_unconsumed_file_and_path_escape_are_blocked(tmp_path):
    files = recording()
    files["bundle/review.json"] = b"{}"
    game = capture(tmp_path, files)
    (tmp_path / "capture/bundle/review.json").write_bytes(b"changed")
    assert audit_game(tmp_path, game)["first_blocker"]["code"] == "source_changed"
    game["files"] = {"../outside": {"sha256": "", "previous_sha256": ""}}
    with pytest.raises(EvidenceError) as error:
        read_capture(tmp_path, game)
    assert error.value.code == "source_path_escape"


def test_failed_adapter_reports_exact_raw_context_and_prior_transition(tmp_path):
    files = recording()
    change_rows(files, lambda rows: rows[1].update(subType="Unreviewed Shot"))
    result = audit_game(tmp_path, capture(tmp_path, files))
    assert result["context_prepared"] and not result["adapter_completed"]
    assert result["transition"] == "validated -> blocked"
    assert result["first_blocker"]["source_indices"] == [1]
    assert (
        result["first_blocker"]["raw_context"][1]["row"]["subType"] == "Unreviewed Shot"
    )


def test_player_minute_drift_fails_even_when_team_totals_match():
    prepared = prepare_recorded(GAME, recording())
    loaded = StatsNbaV3PossessionLoader(prepared.source, prepared.context)
    prepared.box["homeTeam"]["players"][0]["statistics"]["minutes"] = "41:58"
    prepared.box["homeTeam"]["players"][5]["statistics"]["minutes"] = "6:02"
    with pytest.raises(EvidenceError) as error:
        reconcile(loaded, prepared)
    assert error.value.code == "official_minutes"


def test_official_score_disagreement_fails_reconciliation():
    prepared = prepare_recorded(GAME, recording())
    loaded = StatsNbaV3PossessionLoader(prepared.source, prepared.context)
    prepared.box["homeTeam"]["statistics"]["points"] += 1
    with pytest.raises(EvidenceError) as error:
        reconcile(loaded, prepared)
    assert error.value.code == "official_score"


def test_rounded_official_minute_of_sixty_seconds_is_one_more_minute():
    prepared = prepare_recorded(GAME, recording())
    loaded = StatsNbaV3PossessionLoader(prepared.source, prepared.context)
    assert prepared.box["homeTeam"]["players"][0]["statistics"]["minutes"] == "42:00"
    prepared.box["homeTeam"]["players"][0]["statistics"]["minutes"] = "41:60"
    rows = reconcile(loaded, prepared)["player_minutes"]
    assert next(r for r in rows if r["player_id"] == 1)["official_seconds"] == "2520"


def test_invalid_official_minute_seconds_preserve_raw_value_in_diagnostic():
    prepared = prepare_recorded(GAME, recording())
    loaded = StatsNbaV3PossessionLoader(prepared.source, prepared.context)
    prepared.box["homeTeam"]["players"][0]["statistics"]["minutes"] = "41:61"
    with pytest.raises(EvidenceError) as error:
        reconcile(loaded, prepared)
    assert error.value.code == "official_minutes"
    assert error.value.details == {"player_id": 1, "minutes": "41:61"}


def test_stale_roster_evidence_cannot_prepare_context():
    files = recording()
    evidence = json.loads(files[EVIDENCE])
    evidence["boxscore_sha256"] = "stale"
    files[EVIDENCE] = encode(evidence)
    with pytest.raises(EvidenceError) as error:
        prepare_recorded(GAME, files)
    assert error.value.code == "roster_provenance"


def test_corpus_scope_cannot_drop_a_previously_blocked_game(tmp_path):
    game = capture(tmp_path)
    path = inventory(tmp_path, game)
    data = json.loads(path.read_bytes())
    data["games"] = []
    path.write_bytes(encode(data))
    with pytest.raises(EvidenceError) as error:
        audit_inventory(path)
    assert error.value.code == "inventory_scope"


def test_success_is_research_validation_and_never_publication_acceptance(tmp_path):
    path = inventory(tmp_path, capture(tmp_path))
    report = audit_inventory(path)
    assert report["summary"]["statuses"] == {"checks_passed": 1}
    assert report["summary"]["publication_accepted"] == 0
    assert report["games"][0]["full_game_validated"] is False


def test_network_attempt_is_reported_as_error_not_supported_rejection(
    tmp_path, monkeypatch
):
    path = inventory(tmp_path, capture(tmp_path))

    def connect(*args):
        socket.create_connection(("example.invalid", 80))

    monkeypatch.setattr("tools.parity.corpus.prepare_recorded", connect)
    result = audit_inventory(path)["games"][0]
    assert result["status"] == "error"
    assert "network access" in result["first_blocker"]["message"]


def test_output_cannot_overwrite_recordings(tmp_path, monkeypatch):
    path = inventory(tmp_path, capture(tmp_path))
    monkeypatch.setattr(
        "sys.argv",
        [
            "corpus",
            "--worker",
            "--inventory",
            str(path),
            "--output",
            str(tmp_path / "capture/result.json"),
        ],
    )
    with pytest.raises(EvidenceError) as error:
        main()
    assert error.value.code == "output_path"


def test_recorded_evidence_fixtures_are_unique_and_unchanged():
    manifest = json.loads(
        (ROOT / "tests/parity/recorded-evidence-fixtures.json").read_bytes()
    )
    paths = [item["path"] for item in manifest["files"]]
    assert len(paths) == len(set(paths))
    for item in manifest["files"]:
        assert digest((ROOT / item["path"]).read_bytes()) == item["sha256"], item

