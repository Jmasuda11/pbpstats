"""Prove that the oracle independently exposes the previous attempt's drift."""

import json

from tools.parity.reference import ROOT, prepare_reference
from tools.parity.run import compare, worker


def main():
    original = worker(prepare_reference())
    prior = worker(prepare_reference("prior"), provider="prior_v3")
    report = compare(original, prior)
    differing = {
        row["name"] for row in report["results"] if row.get("same_credits") is False
    }
    expected = {
        "interior_jump_first_possession",
        "technical_after_sub_between_regular_fts",
    }
    output = ROOT / ".parity/prior-v3-synthetic.json"
    report.update(reference=original, candidate=prior)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "cases": report["cases"],
                "full_snapshot_statuses": report["statuses"],
                "matching_credit_cases": report["matching_credit_cases"],
                "credit_differences": sorted(differing),
            }
        )
    )
    if (
        report["cases"] != 145
        or report["matching_credit_cases"] != 143
        or differing != expected
    ):
        raise SystemExit("Previously recorded divergences were not reproduced")
    if any(row["status"] in ("rejected", "missing_case") for row in report["results"]):
        raise SystemExit("A rejected or missing case is not a successful audit")


if __name__ == "__main__":
    main()
