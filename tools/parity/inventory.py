"""Read-only inventory of the external season corpus, including blocked games."""

import argparse
from collections import Counter
import json
from pathlib import Path

from tools.parity.reference import ROOT, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingestion-root", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".parity/corpus-inventory.json"
    )
    args = parser.parse_args()
    root = args.ingestion_root.resolve()
    report_path = root / "jump-lookahead-validation.json"
    previous = json.loads(report_path.read_text(encoding="utf-8"))
    games = []
    for game in previous["games"]:
        capture = Path(game["capture"]).resolve()
        if root not in capture.parents:
            raise ValueError(
                "Capture is outside selected ingestion root: " + str(capture)
            )
        files = {}
        for relative, recorded_hash in game.get("source_hashes", {}).items():
            normalized = relative.replace("\\", "/")
            path = (capture / normalized).resolve()
            if capture not in path.parents:
                raise ValueError("Source path escapes capture")
            actual = digest(path.read_bytes()) if path.is_file() else None
            files[normalized] = dict(
                sha256=actual,
                previous_sha256=recorded_hash,
                unchanged=actual == recorded_hash,
            )
        games.append(
            dict(
                game_id=game["game_id"],
                capture=capture.relative_to(root).as_posix(),
                previous_status=game["status"],
                files=files,
            )
        )
    result = dict(
        schema_version=1,
        ingestion_root=str(root),
        previous_report=dict(
            path=report_path.name,
            sha256=digest(report_path.read_bytes()),
            parser_files=previous["parser_files"],
        ),
        games=games,
        counts=dict(Counter(g["previous_status"] for g in games)),
        changed_or_missing_files=sum(
            not f["unchanged"] for g in games for f in g["files"].values()
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "games": len(games),
                "previous_statuses": result["counts"],
                "changed_or_missing_files": result["changed_or_missing_files"],
            }
        )
    )


if __name__ == "__main__":
    main()
