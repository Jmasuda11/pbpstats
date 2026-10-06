"""Compare every audit outcome on the same immutable season inputs."""

import argparse
from collections import Counter
import json
from pathlib import Path

from tools.parity.reference import ROOT, digest


def outcome(game):
    result = {
        key: game[key]
        for key in (
            "status",
            "context_prepared",
            "adapter_completed",
            "full_game_validated",
        )
    }
    if "first_blocker" in game:
        result["first_blocker"] = {
            key: value
            for key, value in game["first_blocker"].items()
            if key != "raw_context"
        }
    return result


def label(result):
    block = result.get("first_blocker")
    return block["stage"] + ": " + block["code"] if block else result["status"]


def compare_audits(before, after):
    for key in ("inventory_sha256", "previous_report"):
        if before[key] != after[key]:
            raise ValueError("Audit comparisons require identical " + key)
    old = {g["game_id"]: g for g in before["games"]}
    new = {g["game_id"]: g for g in after["games"]}
    if (
        len(old) != len(before["games"])
        or len(new) != len(after["games"])
        or set(old) != set(new)
    ):
        raise ValueError("Audit comparison has duplicate or missing games")
    games = []
    for game_id in sorted(old):
        left, right = old[game_id], new[game_id]
        if not left.get("source_hashes") or left["source_hashes"] != right.get(
            "source_hashes"
        ):
            raise ValueError("Unverified or changed sources for " + game_id)
        for key in ("capture", "previous_status"):
            if left[key] != right[key]:
                raise ValueError("Changed {} for {}".format(key, game_id))
        a, b = outcome(left), outcome(right)
        games.append(
            {
                "game_id": game_id,
                "previous_status": left["previous_status"],
                "changed": a != b,
                "before": a,
                "after": b,
            }
        )
    transitions = Counter()
    for game in games:
        if game["changed"]:
            transitions[label(game["before"]), label(game["after"])] += 1
    return {
        "schema_version": 1,
        "scope": "Audit gate outcomes and first blockers; not a possession-output differential",
        "inventory_sha256": before["inventory_sha256"],
        "summary": {
            "games": len(games),
            "changed": sum(g["changed"] for g in games),
            "unchanged": sum(not g["changed"] for g in games),
            "status_transitions": dict(
                Counter(
                    g["before"]["status"] + " -> " + g["after"]["status"] for g in games
                )
            ),
            "blocker_transitions": [
                {"before": a, "after": b, "games": n}
                for (a, b), n in transitions.most_common()
            ],
        },
        "implementation_changes": [
            p
            for p in sorted(
                set(before["implementation_hashes"])
                | set(after["implementation_hashes"])
            )
            if before["implementation_hashes"].get(p)
            != after["implementation_hashes"].get(p)
        ],
        "games": games,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".parity/corpus-outcome-changes.json"
    )
    args = parser.parse_args()
    if args.output.resolve() in (args.before.resolve(), args.after.resolve()):
        raise ValueError("Comparison must not overwrite either audit")
    before, after = args.before.read_bytes(), args.after.read_bytes()
    report = compare_audits(json.loads(before), json.loads(after))
    report.update(before_sha256=digest(before), after_sha256=digest(after))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in report["summary"].items() if k != "blocker_transitions"}
        )
    )


if __name__ == "__main__":
    main()
