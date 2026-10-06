"""Run reproducible differential checks: python -m tools.parity.run."""

import argparse
from collections import Counter
import json
import re
from pathlib import Path
import subprocess
import sys

from tools.parity.reference import ROOT, digest, prepare_reference
from tools.parity.snapshot import first_difference


def worker(package, provider="v2", suite="synthetic", fixtures=None):
    command = [
        sys.executable,
        "-I",
        "-B",
        str(ROOT / "tools/parity/worker.py"),
        "--package",
        str(package),
        "--provider",
        provider,
        "--suite",
        suite,
    ]
    if fixtures:
        command += ["--fixtures", str(fixtures)]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    return json.loads(completed.stdout)


def compare(reference, candidate):
    old = {row["name"]: row for row in reference["results"]}
    new = {row["name"]: row for row in candidate["results"]}
    rows = []
    for name in sorted(set(old) | set(new)):
        left, right = old.get(name), new.get(name)
        row = {"name": name}
        if left is None or right is None:
            row["status"] = "missing_case"
        elif left["status"] != "ok" or right["status"] != "ok":
            row.update(
                status="rejected",
                reference_error=left.get("error"),
                candidate_error=right.get("error"),
            )
        else:
            difference = first_difference(left["snapshot"], right["snapshot"])
            row.update(
                status="different" if difference else "same",
                first_difference=difference,
                same_credits=left["credits"] == right["credits"],
                credit_difference=first_difference(left["credits"], right["credits"]),
            )
            if difference:
                match = re.match(
                    r"\$\.(events|possessions)\[(\d+)\]", difference["path"]
                )
                if match:
                    layer, index = match[1], int(match[2])
                    row["difference_layer"] = layer
                    row["context"] = {
                        "reference": left["snapshot"][layer][
                            max(0, index - 1) : index + 2
                        ],
                        "candidate": right["snapshot"][layer][
                            max(0, index - 1) : index + 2
                        ],
                    }
        rows.append(row)
    return {
        "cases": len(rows),
        "statuses": dict(Counter(row["status"] for row in rows)),
        "matching_credit_cases": sum(row.get("same_credits", False) for row in rows),
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=ROOT)
    parser.add_argument("--provider", choices=("v2", "prior_v3", "v3"), default="v2")
    parser.add_argument(
        "--suite",
        choices=(
            "synthetic",
            "archived",
            "paired",
            "shots",
            "participants",
            "free-throws",
            "team-heaves",
        ),
        default="synthetic",
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".parity/report.json")
    parser.add_argument(
        "--expect-differences",
        action="store_true",
        help="Audit mode only; not a release gate",
    )
    parser.add_argument(
        "--pinned-prior",
        action="store_true",
        help="Use the frozen previous attempt instead of a working checkout",
    )
    args = parser.parse_args()
    reference = prepare_reference()
    fixtures = (
        reference / "tests/data" if args.suite in ("archived", "paired") else None
    )
    old = worker(reference, suite=args.suite, fixtures=fixtures)
    candidate = (
        prepare_reference("prior") if args.pinned_prior else args.candidate.resolve()
    )
    candidate_fixtures = (
        prepare_reference("prior") / "tests/data"
        if args.suite == "paired" and args.provider == "v3"
        else fixtures
    )
    new = worker(candidate, args.provider, args.suite, candidate_fixtures)
    report = compare(old, new)
    report.update(reference=old, candidate=new)
    report["harness_hashes"] = {
        p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
        for p in sorted((ROOT / "tools/parity").rglob("*.py"))
    }
    if args.suite in ("shots", "free-throws"):
        manifests = [ROOT / "tests/parity" / name for name in (
            "shot-vocabulary.json", "free-throw-vocabulary.json",
        )]
        vocabulary = json.loads(manifests[0].read_bytes())
        paths = set(manifests)
        for source in vocabulary["external_recordings"].values():
            paths.add(ROOT / source["path"])
            paths.update(ROOT / p for p in source.get("provenance_files", {}))
        report["evidence_hashes"] = {
            p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in sorted(paths)
        }
    elif args.suite == "team-heaves":
        manifest = ROOT / "tests/parity/team-heave-evidence.json"
        paths = {manifest} | {
            ROOT / o["path"] for o in json.loads(manifest.read_bytes())["observations"]
        }
        report["scope"] = "Versioned extension versus controlled V2 team-miss analogues; not historical V2 parity"
        report["evidence_hashes"] = {
            p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in sorted(paths)
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: report[key] for key in ("cases", "statuses", "matching_credit_cases")}
        )
    )
    for row in report["results"]:
        if row.get("same_credits") is False or row["status"] in (
            "rejected",
            "missing_case",
        ):
            print(
                row["name"],
                row.get("credit_difference")
                or row.get("candidate_error")
                or row["status"],
            )
    if not args.expect_differences and report["statuses"] != {"same": report["cases"]}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
