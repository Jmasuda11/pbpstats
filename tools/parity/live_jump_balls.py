"""Every paired V2 jump ball against the live action with the same number.

The adapter completes jump balls V3 leaves undecided from the league's live
play-by-play. This check is independent of the adapter: for each V2 jump ball
it compares both jumpers, and the recipient or, for a team recovery, the team,
with the live action that carries the same event number. Live files are
recorded responses, one per game, named playbyplay_<game_id>.json.

    python -m tools.parity.live_jump_balls --season nba-2024 --live .parity/live/nba-2024
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def whole_seconds(clock):
    """Seconds remaining, floored, from a live PT11M56.00S or a V2 11:56 clock."""
    if clock.startswith("PT"):
        minutes, seconds = clock[2:-1].split("M")
    else:
        minutes, seconds = clock.split(":")
    return int(minutes) * 60 + int(float(seconds))


def compare(v2_rows, live_actions):
    """(kind, agreement, clock relation, details) for each V2 jump ball."""
    teams = {integer(r.get("PLAYER1_TEAM_ID")) for r in v2_rows} - {None}
    by_number = {}
    for action in live_actions:
        if action.get("actionType") == "jumpball":
            by_number.setdefault(action.get("actionNumber"), []).append(action)
    for row in v2_rows:
        if integer(row["EVENTMSGTYPE"]) != 10:
            continue
        found = by_number.get(integer(row["EVENTNUM"]), [])
        if len(found) != 1:
            yield "unmatched", "no single live action", None, dict(event=row["EVENTNUM"])
            continue
        live = found[0]
        recipient, tip_team = integer(row.get("PLAYER3_ID")), integer(row.get("PLAYER3_TEAM_ID"))
        recovered = live.get("jumpBallRecoverdPersonId")
        checks = dict(
            period=live.get("period") == integer(row["PERIOD"]),
            jumpers={integer(row["PLAYER1_ID"]), integer(row["PLAYER2_ID"])}
            == {live.get("jumpBallWonPersonId"), live.get("jumpBallLostPersonId")},
        )
        if tip_team is None and recipient in teams:
            kind = "team recovery"
            checks["team"] = not recovered and not live.get("personId") and live.get("teamId") == recipient
        else:
            kind = "player tip"
            checks["recipient"] = recovered == recipient
        same_clock = whole_seconds(live["clock"]) == whole_seconds(row["PCTIMESTRING"])
        yield kind, all(checks.values()), same_clock, dict(
            event=row["EVENTNUM"], failed=[k for k, v in checks.items() if not v]
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="nba-2024", help="nba-2024 or wnba-2025")
    parser.add_argument("--live", type=Path, required=True, help="Directory of live responses")
    parser.add_argument("--output", type=Path, help="Default: .parity/live-jump-balls-<season>.json")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from tools.parity.paired_season import season

    v2, v3, _ = season(args.season)
    games, counts, disagreements, files = sorted(set(v2) & set(v3)), Counter(), [], {}
    for game_id in games:
        path = args.live / "playbyplay_{}.json".format(game_id)
        if not path.exists():
            counts["games without a live response"] += 1
            continue
        raw = path.read_bytes()
        files[game_id] = hashlib.sha256(raw).hexdigest()
        game = json.loads(raw)["game"]
        if game["gameId"] != game_id:
            raise ValueError("Live response game identity disagrees: " + str(path))
        for kind, agrees, same_clock, details in compare(v2[game_id], game["actions"]):
            counts["{}: {}{}".format(kind, "agrees" if agrees else "DISAGREES",
                                     "" if same_clock in (True, None) else ", other clock")] += 1
            if not agrees:
                disagreements.append(dict(game_id=game_id, kind=kind, **details))
    report = dict(
        schema_version=1,
        season=args.season,
        scope="Each V2 jump ball against the live action with the same number; independent of the adapter",
        games=len(games),
        counts=dict(sorted(counts.items())),
        disagreements=disagreements,
        live_files=files,
    )
    output = args.output or ROOT / ".parity/live-jump-balls-{}.json".format(args.season)
    output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(dict(counts=report["counts"], disagreements=len(disagreements)), indent=1))


if __name__ == "__main__":
    main()
