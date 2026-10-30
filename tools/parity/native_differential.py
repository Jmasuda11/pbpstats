"""Compare this checkout's V3 parser with the pinned oracle, game by game.

The oracle is the revision pinned as ``oracle`` in tests/parity/manifest.json.
Each side parses the same recorded games the way an import does (reviewed
overrides, then ``web.load_game``), offline, in its own worker processes, and
records what the original's event classes decide. The two records of each game
are then compared field by field.

Games are read from capture bundles (``--bundles``) or from flat recorded
evidence (``--recorded``, by default tests/parity/data/recorded_evidence).
"""

import argparse
from collections import Counter
from contextlib import redirect_stdout
from decimal import Decimal
import hashlib
import io
import json
from multiprocessing import get_context
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from types import SimpleNamespace

from tools.parity.reference import prepare_reference

ROOT = Path(__file__).resolve().parents[2]
RECORDED = ROOT / "tests/parity/data/recorded_evidence"

# What the original's classes (e7ccf2f) decide, by event family. A name ending
# in "()" is a method; an event-valued property is recorded as its number.
COMMON = [
    "seconds_remaining",
    "seconds_since_previous_event",
    "score_margin",
    "is_possession_ending_event",
    "count_as_possession",
    "get_offense_team_id()",
    "is_second_chance_event()",
    "is_penalty_event()",
]
DECISIONS = {
    "FieldGoal": [
        "is_made", "shot_value", "distance", "shot_type", "is_corner_3", "is_heave",
        "is_putback", "is_assisted", "is_blocked", "is_and1",
        "is_make_that_does_not_end_possession", "rebound",
    ],
    "FreeThrow": [
        "is_made", "shot_value", "free_throw_type", "num_ft_for_trip", "is_first_ft",
        "is_end_ft", "is_ft_1_of_1", "is_ft_1_of_2", "is_ft_2_of_2", "is_ft_1_of_3",
        "is_ft_2_of_3", "is_ft_3_of_3", "is_ft_1pt", "is_ft_2pt", "is_ft_3pt",
        "is_technical_ft", "is_flagrant_ft", "is_away_from_play_ft",
        "is_inbound_foul_ft", "is_transition_take_foul_ft", "foul_that_led_to_ft",
        "event_for_efficiency_stats",
    ],
    "Rebound": [
        "is_real_rebound", "is_placeholder", "is_buzzer_beater_placeholder",
        "is_buzzer_beater_rebound_at_shot_time", "is_non_live_ft_placeholder",
        "is_turnover_placeholder", "oreb", "self_reb", "missed_shot",
    ],
    "Turnover": [
        "is_no_turnover", "is_steal", "is_bad_pass", "is_bad_pass_out_of_bounds",
        "is_lost_ball", "is_lost_ball_out_of_bounds", "is_travel",
        "is_shot_clock_violation", "is_3_second_violation", "is_offensive_goaltending",
        "is_kicked_ball", "is_lane_violation", "is_step_out_of_bounds",
    ],
    "Foul": [
        "foul_type_string", "number_of_fta_for_foul", "counts_as_personal_foul",
        "counts_towards_penalty", "is_personal_foul", "is_shooting_foul",
        "is_loose_ball_foul", "is_offensive_foul", "is_charge",
        "is_personal_block_foul", "is_personal_take_foul", "is_shooting_block_foul",
        "is_inbound_foul", "is_away_from_play_foul", "is_clear_path_foul",
        "is_double_foul", "is_technical", "is_double_technical", "is_delay_of_game",
        "is_defensive_3_seconds", "is_flagrant", "is_flagrant1", "is_flagrant2",
        "is_transition_take_foul",
    ],
    "Violation": [
        "is_delay_of_game", "is_goaltend_violation", "is_lane_violation",
        "is_double_lane_violation", "is_jumpball_violation", "is_kicked_ball_violation",
    ],
    "Substitution": ["incoming_player_id", "outgoing_player_id"],
    "JumpBall": ["winning_team"],
    "Replay": ["support_ruling", "overturn_ruling", "ruling_stands"],
    "StartOfPeriod": ["league", "get_team_starting_with_ball()"],
    "Timeout": [],
    "Ejection": [],
    "EndOfPeriod": [],
}
POSSESSION = [
    "offense_team_id",
    "start_time",
    "end_time",
    "start_score_margin",
    "possession_start_type",
    "possession_has_timeout",
    "previous_possession_has_timeout",
    "previous_possession_ending_event",
    "previous_possession_end_shooter_player_id",
    "previous_possession_end_rebound_player_id",
    "previous_possession_end_steal_player_id",
    "previous_possession_end_turnover_player_id",
]


# ---------------------------------------------------------------- recorded games


def game(game_id, pbp, boxscore, starters, live):
    return dict(
        id=game_id,
        pbp=str(pbp),
        boxscore=str(boxscore),
        starters={path.stem.rsplit("_", 1)[1]: str(path) for path in starters},
        live=str(live) if live.exists() else None,
    )


def bundle_games(root):
    """Capture bundles: bundle/pbp, bundle/game_details, bundle/starters, bundle/live.
    A game's last bundle in path order is used."""
    games = {}
    for pbp in sorted(Path(root).rglob("pbp/stats_v3_*.json")):
        bundle, game_id = pbp.parents[1], pbp.stem[len("stats_v3_"):]
        box = bundle / "game_details" / f"stats_v3_boxscore_{game_id}.json"
        if box.exists():
            # *[0-9].json leaves out each recording's .source.json
            starters = (bundle / "starters").glob("boxscoretraditionalv2_period_*[0-9].json")
            live = bundle / "live" / f"playbyplay_{game_id}.json"
            games[game_id] = game(game_id, pbp, box, starters, live)
    return games


def recorded_games(folder):
    """Flat recorded evidence, as kept in tests/parity/data/recorded_evidence."""
    games = {}
    for pbp in sorted(Path(folder).glob("stats_v3_[0-9]*.json")):
        game_id = pbp.stem[len("stats_v3_"):]
        box = pbp.with_name(f"stats_v3_boxscore_{game_id}.json")
        if box.exists():
            starters = pbp.parent.glob(f"stats_boxscoretraditionalv2_{game_id}_period_*.json")
            live = pbp.with_name(f"live_{game_id}.json")
            games[game_id] = game(game_id, pbp, box, starters, live)
    return games


# ---------------------------------------------------------------- observing one game


def plain(value):
    """JSON data with exact numbers; an event becomes its number."""
    if hasattr(value, "event_num"):
        return value.event_num
    if isinstance(value, (float, Decimal)):
        number = Decimal(str(value)).normalize()
        return int(number) if number == number.to_integral_value() else str(number)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def attempt(get):
    """The value, or the error raised getting it: errors are observations too."""
    try:
        return plain(get())
    except Exception as error:
        return {"error": type(error).__name__, "message": str(error)[:200]}


def decide(item, name):
    if name.endswith("()"):
        return attempt(lambda: getattr(item, name[:-2])())
    return attempt(lambda: getattr(item, name))


def stats_digest(rows):
    rows = sorted(json.dumps(plain(row), sort_keys=True) for row in rows)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def event_record(event):
    from pbpstats.resources import enhanced_pbp

    families = [f for f in DECISIONS if isinstance(event, getattr(enhanced_pbp, f))]
    record = dict(
        families=families,
        period=event.period,
        clock=attempt(lambda: event.clock),
        previous=plain(event.previous_event),
        next=plain(event.next_event),
        lineups=attempt(lambda: event.lineup_ids),
        score=attempt(lambda: {t: event.score.get(t, 0) for t in event.current_players}),
        stats=attempt(lambda: stats_digest(event.event_stats)),
        description=attempt(lambda: event.description),
        source_rows=attempt(lambda: event.v3_source_indices),
    )
    # An absent participant attribute decides differently from a None one.
    for name in ("team_id", "player1_id", "player2_id", "player3_id"):
        record[name] = getattr(event, name) if hasattr(event, name) else "absent"
    for name in COMMON + [name for f in families for name in DECISIONS[f]]:
        record[name] = decide(event, name)
    return record


def possession_record(possession):
    record = dict(
        events=[event.event_num for event in possession.events],
        stats=attempt(lambda: stats_digest(possession.possession_stats)),
    )
    for name in POSSESSION:
        record[name] = decide(possession, name)
    return record


def team_totals(events):
    totals = Counter()
    for event in events:
        try:
            rows = event.event_stats
        except Exception:
            continue  # the event's own record shows the error
        for row in rows:
            totals[f"{row['team_id']}|{row['stat_key']}"] += Decimal(str(row["stat_value"]))
    return plain(dict(totals))


def game_record(loader):
    events = {}
    for event in loader.events:
        if str(event.event_num) in events:
            raise ValueError(f"Two events are numbered {event.event_num}")
        events[str(event.event_num)] = event_record(event)
    return dict(
        status="parsed",
        order=[event.event_num for event in loader.events],
        events=events,
        possessions={f"{p.period}:{p.number}": possession_record(p) for p in loader.items},
        counts=attempt(lambda: loader.counts_by_team),
        totals=team_totals(loader.events),
        capabilities=attempt(lambda: loader.capabilities),
        diagnostics=attempt(
            lambda: sorted(json.dumps(plain(d), sort_keys=True) for d in loader.diagnostics)
        ),
    )


def parse(game):
    """Parse one recorded game as an import does, offline."""
    from pbpstats.data_loader.stats_nba_v3 import V3EvidenceRequired, web

    pbp = Path(game["pbp"]).read_bytes()
    box = Path(game["boxscore"]).read_bytes()
    teams = json.loads(box)["boxScoreTraditional"]
    players = {p["personId"] for team in ("homeTeam", "awayTeam") for p in teams[team]["players"]}
    # As an import does, aliases apply only to players in the box score.
    aliases = {int(k): v for k, v in game["aliases"].items() if int(k) in players}

    def fetch_boxscore(period, url, params):
        if str(period) not in game["starters"]:
            raise V3EvidenceRequired(
                f"Period {period} starter box score is not recorded",
                period=period, url=url, params=params,
            )
        content = Path(game["starters"][str(period)]).read_bytes()
        return SimpleNamespace(content=content, url=url, status_code=200, reason="OK")

    def fetch_live(url):
        return SimpleNamespace(content=Path(game["live"]).read_bytes(), url=url)

    return web.load_game(
        game["id"],
        pbp,
        box,
        game["pbp"],
        fetch_boxscore=fetch_boxscore,
        aliases=aliases,
        overrides=web.reviewed_overrides(game["id"], pbp),
        fetch_live=fetch_live if game["live"] else None,
    )


def observe(game):
    try:
        with redirect_stdout(io.StringIO()):
            loader = parse(game)
    except Exception as error:
        return dict(
            status="rejected",
            error=type(error).__name__,
            module=type(error).__module__,
            message=str(error),
        )
    try:
        return game_record(loader)
    except Exception as error:
        # A parsed game that cannot be observed is a harness or parser defect.
        return dict(status="unobservable", error=type(error).__name__, message=str(error))


def start_worker(package):
    """Import the parser from ``package`` only, with the network blocked."""

    def offline(*args, **kwargs):
        raise RuntimeError("A comparison worker attempted network access")

    socket.socket.connect = socket.create_connection = offline
    sys.path.insert(0, package)
    import pbpstats

    expected = Path(package, "pbpstats", "__init__.py").resolve()
    if Path(pbpstats.__file__).resolve() != expected:
        raise RuntimeError("Wrong parser imported: " + pbpstats.__file__)


# ---------------------------------------------------------------- comparing


def differences(old, new, path="$"):
    """Every path at which two records differ."""
    if isinstance(old, dict) and isinstance(new, dict):
        found = []
        for key in sorted(set(old) | set(new)):
            a, b = old.get(key, "missing"), new.get(key, "missing")
            found += differences(a, b, f"{path}.{key}")
        return found
    return [] if old == new else [dict(path=path, oracle=old, candidate=new)]


def generic(path):
    """$.events.412.is_and1 -> $.events.*.is_and1"""
    return re.sub(r"\.[\d:]+(?=\.|$)", ".*", path)


def compare(game_id, old, new):
    found = differences(old, new)
    if found:
        return dict(
            game=game_id,
            outcome="differs",
            fields=sorted({generic(d["path"]) for d in found}),
            differences=found[:20],
        )
    if old["status"] == "parsed":
        return dict(game=game_id, outcome="identical")
    return dict(game=game_id, outcome="both_" + old["status"], error=old["error"])


def compare_all(oracle, games, jobs):
    """Observe every game on both sides at once, comparing as results arrive."""
    spawn = get_context("spawn")
    old = spawn.Pool(jobs, start_worker, (str(oracle),))
    new = spawn.Pool(jobs, start_worker, (str(ROOT),))
    with old, new:
        results = zip(games, old.imap(observe, games, 4), new.imap(observe, games, 4))
        for count, (game, a, b) in enumerate(results, 1):
            yield compare(game["id"], a, b)
            if count % 500 == 0:
                print(f"{count}/{len(games)}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundles", type=Path, action="append", default=[])
    parser.add_argument("--recorded", type=Path, action="append", default=[])
    parser.add_argument("--aliases", type=Path, help="Reviewed aliases: {personId: [names]}")
    parser.add_argument("--game", action="append", help="Only these game IDs")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2 - 1))
    parser.add_argument("--output", type=Path, default=ROOT / ".parity/native-differential.json")
    args = parser.parse_args()

    found = {}
    for root in args.bundles:
        found.update(bundle_games(root))
    for folder in args.recorded or ([] if args.bundles else [RECORDED]):
        found.update(recorded_games(folder))
    aliases = json.loads(args.aliases.read_text(encoding="utf-8")) if args.aliases else {}
    games = [
        dict(found[g], aliases=aliases) for g in sorted(found) if not args.game or g in args.game
    ]
    if not games:
        parser.error("No recorded games found")

    manifest = json.loads((ROOT / "tests/parity/manifest.json").read_bytes())
    rows = list(compare_all(prepare_reference("oracle"), games, args.jobs))
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True)
    report = dict(
        oracle=manifest["oracle_revision"],
        candidate=head.strip(),
        games=len(rows),
        outcomes=Counter(row["outcome"] for row in rows),
        rejections=Counter(row["error"] for row in rows if "error" in row),
        rejected_games={row["game"]: row["error"] for row in rows if "error" in row},
        # In how many games each field differs.
        differing_fields=Counter(field for row in rows for field in row.get("fields", [])),
        differing_games=[row for row in rows if row["outcome"] == "differs"],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["outcomes"]))


if __name__ == "__main__":
    main()
