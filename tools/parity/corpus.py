"""Offline, isolated audit of every game in the frozen season inventory."""

import argparse
from collections import Counter
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
from unittest.mock import patch

# The subprocess is launched with -I; never discover a prior editable install.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pbpstats
from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader, V3DecodeError
from pbpstats.resources.enhanced_pbp.rebound import EventOrderError
from pbpstats.resources.enhanced_pbp.start_of_period import (
    InvalidNumberOfStartersException,
)
from pbpstats.data_loader.stats_nba.possessions.loader import (
    TeamHasBackToBackPossessionsException,
)
from tools.parity.recorded import (
    EvidenceError,
    VERSION,
    contained,
    prepare_recorded,
    read_capture,
    reconcile,
    require,
)
from tools.parity.reference import ROOT, digest
from tools.parity.recorded_supplements import evidence_hashes


def offline(*args, **kwargs):
    raise RuntimeError("Corpus audit attempted network access")


def blocker(error, stage, rows):
    details = getattr(error, "details", {})
    message = str(error)
    code = getattr(error, "code", type(error).__name__)
    if isinstance(error, V3DecodeError):
        code = re.sub(r"^Game .+?, source rows \[[^]]*\]: ", "", message)
        # Keep vocabulary categories; do not create one category per player name.
        if code.startswith("Participant "):
            code = "unresolved_or_ambiguous_participant"
    indices = []
    if "source_index" in details:
        indices = [details["source_index"]]
    match = re.search(r"source rows (\[[0-9, ]*\])", message)
    if match:
        indices = json.loads(match[1])
    return {
        "stage": stage,
        "code": code,
        "exception": type(error).__name__,
        "message": message,
        "details": details,
        "source_indices": indices,
        "raw_context": [
            {"source_index": i, "row": rows[i]}
            for i in sorted(
                {
                    j
                    for i in indices
                    for j in range(max(0, i - 1), min(len(rows), i + 2))
                }
            )
        ],
    }


def audit_game(root, game):
    result = {
        "game_id": game["game_id"],
        "capture": game["capture"],
        "previous_status": game["previous_status"],
        "status": "blocked",
        "context_prepared": False,
        "adapter_completed": False,
        "full_game_validated": False,
    }
    stage, rows = "source_integrity", []
    try:
        files = read_capture(root, game)
        result["source_hashes"] = {p: digest(data) for p, data in files.items()}
        stage = "preparation"
        raw = files.get("bundle/pbp/stats_v3_{}.json".format(game["game_id"]))
        if raw is not None:
            rows = json.loads(raw).get("game", {}).get("actions", [])
        prepared = prepare_recorded(game["game_id"], files)
        result.update(context_prepared=True, preparation=prepared.provenance)
        rows = prepared.rows
        stage = "adapter"
        output = io.StringIO()
        with redirect_stdout(output):
            loaded = StatsNbaV3PossessionLoader(prepared.source, prepared.context)
        result.update(
            adapter_completed=True,
            capabilities=loaded.capabilities,
            events=len(loaded.events),
            possessions=len(loaded.items),
            credited_possessions=loaded.counts_by_team,
            repairs=loaded.diagnostics,
            participant_resolutions=loaded.decoded.participant_resolutions,
        )
        if output.getvalue():
            result["loader_output"] = output.getvalue()
        stage = "reconciliation"
        result["reconciliation"] = reconcile(loaded, prepared)
        result["status"] = "checks_passed"
    except (
        EvidenceError,
        V3DecodeError,
        EventOrderError,
        InvalidNumberOfStartersException,
        TeamHasBackToBackPossessionsException,
    ) as error:
        result["first_blocker"] = blocker(error, stage, rows)
    except Exception as error:
        # An implementation crash is never classified as a supported rejection.
        result.update(status="error", first_blocker=blocker(error, stage, rows))
    result["transition"] = game["previous_status"] + " -> " + result["status"]
    return result


def audit_inventory(inventory_path, progress=False):
    imported = Path(pbpstats.__file__).resolve()
    require(
        imported == ROOT / "pbpstats/__init__.py",
        "package_isolation",
        "Wrong pbpstats package imported",
    )
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    root = Path(inventory["ingestion_root"]).resolve()
    previous_bytes = contained(root, inventory["previous_report"]["path"]).read_bytes()
    require(
        digest(previous_bytes) == inventory["previous_report"]["sha256"],
        "previous_report_changed",
        "Previous report no longer matches inventory",
    )
    previous = json.loads(previous_bytes)
    games = inventory["games"]
    require(
        len({g["game_id"] for g in games}) == len(games)
        and len({g["game_id"] for g in previous["games"]}) == len(previous["games"]),
        "inventory_scope",
        "Duplicate game IDs in audit scope",
    )
    require(
        {g["game_id"]: g["previous_status"] for g in games}
        == {g["game_id"]: g["status"] for g in previous["games"]},
        "inventory_scope",
        "Inventory omits or changes previous outcomes",
    )
    for old, game in zip(
        sorted(previous["games"], key=lambda g: g["game_id"]),
        sorted(games, key=lambda g: g["game_id"]),
    ):
        require(
            contained(root, game["capture"]) == Path(old["capture"]).resolve()
            and {
                p.replace("\\", "/"): f["previous_sha256"]
                for p, f in game["files"].items()
            }
            == {p.replace("\\", "/"): h for p, h in old["source_hashes"].items()},
            "inventory_scope",
            "Inventory changes capture or source manifest",
            game_id=game["game_id"],
        )
    results = []
    with ExitStack() as stack:
        for target in ("connect", "connect_ex"):
            stack.enter_context(patch.object(socket.socket, target, offline))
        stack.enter_context(patch.object(socket, "create_connection", offline))
        for index, game in enumerate(games, 1):
            results.append(audit_game(root, game))
            if progress and index % 100 == 0:
                print(
                    "Audited {}/{} games".format(index, len(games)),
                    file=sys.stderr,
                    flush=True,
                )
    codes = Counter(
        (r["first_blocker"]["stage"], r["first_blocker"]["code"])
        for r in results
        if "first_blocker" in r
    )
    return {
        "schema_version": 1,
        "preparation_version": VERSION,
        "scope": "offline research validation; not historical V2 parity or publication acceptance",
        "inventory_sha256": digest(inventory_bytes),
        "previous_report": inventory["previous_report"],
        "package": str(imported),
        "network_disabled": True,
        "implementation_hashes": {
            p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
            for folder in (ROOT / "pbpstats", ROOT / "tools/parity")
            for p in sorted(folder.rglob("*.py"))
        },
        "supplemental_evidence_hashes": evidence_hashes(),
        "summary": {
            "games": len(results),
            "statuses": dict(Counter(r["status"] for r in results)),
            "context_prepared": sum(r["context_prepared"] for r in results),
            "adapter_completed": sum(r["adapter_completed"] for r in results),
            "publication_accepted": 0,
            "transitions": dict(Counter(r["transition"] for r in results)),
            "first_blockers": [
                {"stage": stage, "code": code, "games": count}
                for (stage, code), count in codes.most_common()
            ],
        },
        "games": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory", type=Path, default=ROOT / ".parity/corpus-inventory.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".parity/candidate-v3-corpus.json"
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail if any research check is blocked",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.worker:
        command = [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "--worker",
            "--inventory",
            str(args.inventory.resolve()),
            "--output",
            str(args.output.resolve()),
        ]
        if args.require_all:
            command.append("--require-all")
        raise SystemExit(subprocess.run(command, cwd=ROOT, timeout=1800).returncode)
    inventory = json.loads(args.inventory.read_bytes())
    root, output = Path(inventory["ingestion_root"]).resolve(), args.output.resolve()
    require(
        root != output
        and root not in output.parents
        and output != args.inventory.resolve(),
        "output_path",
        "Report must not overwrite the inventory or source corpus",
    )
    report = audit_inventory(args.inventory, progress=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"]))
    if report["summary"]["statuses"].get("error"):
        raise SystemExit(2)
    if args.require_all and report["summary"]["statuses"].get("blocked"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
