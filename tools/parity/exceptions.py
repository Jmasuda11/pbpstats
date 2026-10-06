"""Compare declared failures and recoveries: python -m tools.parity.exceptions."""

import argparse
from collections import Counter
import json
from pathlib import Path

from tools.parity.exception_cases import catalog
from tools.parity.reference import ROOT, digest, prepare_reference
from tools.parity.run import worker
from tools.parity.snapshot import first_difference


EXCEPTION_MODULES = {
    "TeamHasBackToBackPossessionsException": "pbpstats.data_loader.stats_nba.possessions.loader",
    "EventOrderError": "pbpstats.resources.enhanced_pbp.rebound",
    "InvalidNumberOfStartersException": "pbpstats.resources.enhanced_pbp.start_of_period",
}
MATCHES = {"expected_exception_matched", "return_matched"}
FAILURE_MODULES = dict(
    EXCEPTION_MODULES,
    HTTPError="requests.exceptions",
    JSONDecodeError="requests.exceptions",
    KeyError="builtins",
    IndexError="builtins",
    UnboundLocalError="builtins",
)


def expected_outcome(result, case):
    expected = case["expected_exception"]
    outcome = result.get("outcome", {})
    if (
        result.get("expected_exception") != expected
        or result.get("boundary") != case["boundary"]
        or result.get("status") != "observed"
        or result.get("fixture_sha256")
        != digest(json.dumps(case, sort_keys=True).encode())
    ):
        return False
    if expected is None:
        return outcome.get("kind") == "return" and "value" in outcome
    return (
        outcome.get("kind") == "exception"
        and outcome.get("type") == expected
        and outcome.get("module") == FAILURE_MODULES[expected]
        and isinstance(outcome.get("message"), str)
        and bool(outcome["message"])
    )


def compare_exceptions(reference, candidate):
    cases = {case["name"]: case for case in catalog()}
    reports = []
    for report in (reference, candidate):
        names = [r["name"] for r in report["results"]]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate exception case")
        reports.append({r["name"]: r for r in report["results"]})
    rows = []
    for name in sorted(set(cases) | set(reports[0]) | set(reports[1])):
        left, right, case = reports[0].get(name), reports[1].get(name), cases.get(name)
        row = dict(name=name)
        if left is None or right is None or case is None:
            row["status"] = "missing_or_unknown_case"
        elif not all(expected_outcome(result, case) for result in (left, right)):
            row.update(status="unexpected_outcome", reference=left, candidate=right)
        else:
            difference = first_difference(left["outcome"], right["outcome"])
            row.update(
                boundary=case["boundary"],
                status=(
                    "different"
                    if difference
                    else (
                        "expected_exception_matched"
                        if case["expected_exception"]
                        else "return_matched"
                    )
                ),
                first_difference=difference,
            )
        rows.append(row)
    return dict(
        cases=len(rows),
        statuses=dict(Counter(r["status"] for r in rows)),
        complete=all(r["status"] in MATCHES for r in rows),
        results=rows,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=ROOT)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".parity/exception-parity.json"
    )
    args = parser.parse_args()
    reference = worker(prepare_reference(), suite="exceptions")
    candidate = worker(args.candidate.resolve(), provider="v3", suite="exceptions")
    report = compare_exceptions(reference, candidate)
    report.update(
        scope="Declared parser failure/recovery fixtures, not successful-game or exhaustive exception parity",
        reference=reference,
        candidate=candidate,
        harness_hashes={
            name: digest((ROOT / "tools/parity" / name).read_bytes())
            for name in (
                "exception_cases.py",
                "exceptions.py",
                "worker.py",
                "scenarios.py",
                "starter_cases.py",
            )
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cases", "statuses", "complete")}))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
