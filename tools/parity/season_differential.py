"""Original V2 engine versus the V3 adapter, game by game, on the paired season.

Each game runs in isolated worker processes with network access disabled: the
pinned original on its V2 export through the original file loader, and the
candidate on the same game's V3 export in three modes:

- ``exact``: the V3 export as recorded, the production-equivalent input;
- ``floor``: clocks floored to whole seconds, the projection V2 records;
- ``floor_v2_order``: also V2's order within each clock instant. This mode
  reads one V2 fact (event order) and is a diagnostic of translation fidelity,
  never a production input.

Otherwise the V3 side reads no V2 fact. The pinned evidence has no V2 shot
chart, so the original's shot coordinate files come from the V3 export's
xLegacy/yLegacy; the report declares that shared input. V3 lacks the fouled
player, so foul ``player3_id`` and fouls-drawn statistics are reported as a
separate known gap. Results are research comparisons, not acceptance.
"""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[2]
CLOCK = re.compile(r"PT(\d+)M(\d+)(?:\.\d+)?S")
V2_INTEGERS = {
    "EVENTNUM",
    "EVENTMSGTYPE",
    "EVENTMSGACTIONTYPE",
    "PERIOD",
    "PERSON1TYPE",
    "PLAYER1_ID",
    "PLAYER1_TEAM_ID",
    "PERSON2TYPE",
    "PLAYER2_ID",
    "PLAYER2_TEAM_ID",
    "PERSON3TYPE",
    "PLAYER3_ID",
    "PLAYER3_TEAM_ID",
    "VIDEO_AVAILABLE_FLAG",
}
SHOT_HEADERS = ["GAME_ID", "GAME_EVENT_ID", "PLAYER_ID", "TEAM_ID", "LOC_X", "LOC_Y"]
MODES = ("exact", "floor", "floor_v2_order")
FOULS_DRAWN = "Fouls Drawn"
SUBSTITUTION = re.compile(r"SUB: (.+) FOR (.+)")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


# ---------------------------------------------------------------- inputs


def v2_payload(game_id, rows):
    """Recorded V2 JSON shape: integer columns typed, blank cells null."""
    headers = list(rows[0])

    def value(key, text):
        if text == "":
            return None
        if key == "GAME_ID":
            return text.zfill(10)
        return int(text) if key in V2_INTEGERS else text

    rows = [[value(key, row[key]) for key in headers] for row in rows]
    return {
        "resource": "playbyplay",
        "parameters": {"GameID": game_id},
        "resultSets": [{"name": "PlayByPlay", "headers": headers, "rowSet": rows}],
    }


def shot_payloads(game_id, actions):
    """Original shot-chart files from the V3 export's own coordinates."""
    sides = {"h": [], "v": []}
    for action in actions:
        if action["actionType"] in ("Made Shot", "Missed Shot"):
            sides["h" if action["location"] == "h" else "v"].append(
                [
                    game_id,
                    action["actionNumber"],
                    action["personId"],
                    action["teamId"],
                    action["xLegacy"],
                    action["yLegacy"],
                ]
            )
    return {
        side: {
            "resultSets": [
                {"name": "Shot_Chart_Detail", "headers": SHOT_HEADERS, "rowSet": rows}
            ]
        }
        for side, rows in sides.items()
    }


def floored(actions):
    """The named comparison projection: whole seconds, as V2 records them."""
    result = []
    for action in actions:
        match = CLOCK.fullmatch(action["clock"])
        result.append(dict(action, clock="PT{}M{}.00S".format(match[1], match[2])))
    return result


def in_v2_order(actions, rows):
    """Diagnostic only: V3 action groups in V2's within-instant order."""
    position = {}
    for row in rows:
        position.setdefault(int(row["EVENTNUM"]), len(position))
    groups = defaultdict(list)
    for action in actions:
        groups[action["actionNumber"]].append(action)
    return [
        a for number in sorted(groups, key=position.__getitem__) for a in groups[number]
    ]


def season_names(v3):
    """Team -> casefolded name -> player IDs, from every game's own V3 actors."""
    from tools.parity.participant_names import unaccented

    index = defaultdict(lambda: defaultdict(set))
    names = defaultdict(set)
    for actions in v3.values():
        teams = {a["teamId"] for a in actions if a["teamId"]}
        for action in actions:
            identity, team = action["personId"], action["teamId"]
            if identity and identity not in teams and team in teams:
                for name in (action["playerName"], action["playerNameI"]):
                    if name.strip():
                        names[identity, team].update({name, unaccented(name)})
    for (identity, team), values in names.items():
        for name in values:
            index[team][name.casefold()].add(identity)
    return index, names


def v3_context(game_id, actions, season_index=None, season="2024-25"):
    """Teams and roster from V3 actors and their own descriptions.

    A substitute who never acts in this game is named only in the description.
    Such a name may be bound to the unique same-team player with that name in
    this season's other V3 actor rows; ambiguous names stay unresolved.
    """
    from tools.parity.participant_names import roster_from_actors
    from tools.parity.recorded import require

    sides = defaultdict(set)
    for action in actions:
        if action["location"] in ("h", "v") and action["teamId"]:
            sides[action["location"]].add(action["teamId"])
    require(
        set(sides) == {"h", "v"}
        and all(len(teams) == 1 for teams in sides.values())
        and sides["h"] != sides["v"],
        "team_identity",
        "Home and away teams are not uniquely recorded",
    )
    teams = (next(iter(sides["h"])), next(iter(sides["v"])))
    roster = roster_from_actors(actions, teams, require)
    season_bound = []
    if season_index is not None:
        index, names = season_index
        known = {
            (facts["team_id"], name.casefold())
            for facts in roster.values()
            for name in facts["names"]
        }
        for action in actions:
            match = SUBSTITUTION.fullmatch(action["description"])
            if action["actionType"] != "Substitution" or not match:
                continue
            team, name = action["teamId"], match[1].strip()
            candidates = index[team].get(name.casefold(), set())
            if (team, name.casefold()) in known or len(candidates) != 1:
                continue
            identity = next(iter(candidates))
            if identity in roster:
                continue
            roster[identity] = {"team_id": team, "names": sorted(names[identity, team])}
            known.update((team, n.casefold()) for n in roster[identity]["names"])
            season_bound.append(dict(player_id=identity, team_id=team, name=name))
    return {
        "team_ids": list(teams),
        "roster": {str(identity): facts for identity, facts in roster.items()},
        "season_bound_substitutes": season_bound,
        "source": "Paired {} V3 export; roster from V3 actors only".format(season),
    }


def prepare(folder, game_ids, v2, v3, season="2024-25"):
    """Write every worker input; return unavailable contexts and season bindings."""
    unavailable, bound = {}, {}
    season_index = season_names(v3)
    for game_id in game_ids:
        (folder / "v2/pbp").mkdir(parents=True, exist_ok=True)
        (folder / "v2/game_details").mkdir(parents=True, exist_ok=True)
        (folder / "v2/pbp/stats_{}.json".format(game_id)).write_bytes(
            canonical(v2_payload(game_id, v2[game_id]))
        )
        for side, payload in shot_payloads(game_id, v3[game_id]).items():
            name = "stats_{}_shots_{}.json".format(
                "home" if side == "h" else "away", game_id
            )
            (folder / "v2/game_details" / name).write_bytes(canonical(payload))
        try:
            context = v3_context(game_id, v3[game_id], season_index, season)
        except ValueError as error:
            unavailable[game_id] = dict(
                category="v3_context: " + getattr(error, "code", "error"),
                message=str(error),
            )
            continue
        if context["season_bound_substitutes"]:
            bound[game_id] = context["season_bound_substitutes"]
        (folder / "v3/context").mkdir(parents=True, exist_ok=True)
        (folder / "v3/context/{}.json".format(game_id)).write_bytes(canonical(context))
        for mode in MODES:
            actions = v3[game_id]
            if mode != "exact":
                actions = floored(actions)
            if mode == "floor_v2_order":
                actions = in_v2_order(actions, v2[game_id])
            (folder / "v3" / mode).mkdir(parents=True, exist_ok=True)
            payload = {"game": {"gameId": game_id, "actions": actions}}
            (folder / "v3" / mode / "{}.json".format(game_id)).write_bytes(
                canonical(payload)
            )
    return unavailable, bound


# ---------------------------------------------------------------- workers


def offline(*args, **kwargs):
    raise RuntimeError("Season worker attempted network access")


def error_category(error):
    frames = {frame.name for frame in traceback.extract_tb(error.__traceback__)}
    name, message = type(error).__name__, str(error)
    if "_get_starters_from_boxscore_request" in frames:
        return "starter_boxscore_needed"
    if "_use_data_nba_event_order" in frames:
        return "provider_order_needed"
    if name == "TeamHasBackToBackPossessionsException":
        return "back_to_back_possessions"
    if name == "V3DecodeError":
        reason = re.sub(r"^Game .+?, source rows \[[^]]*\]: ", "", message)
        if reason.startswith("Participant "):
            reason = "unresolved_or_ambiguous_participant"
        return "v3_decode: " + reason
    return name


def stat_totals(loaded):
    """Exact Decimal totals of the original per-event statistics.

    Fouls-drawn statistics are kept apart: V3 does not record the fouled player.
    """
    totals = {
        part: (defaultdict(Decimal), defaultdict(Decimal))
        for part in ("comparable", "fouls_drawn")
    }
    errors = Counter()
    for event in loaded.events:
        try:
            rows = event.event_stats
        except Exception as error:
            errors[type(event).__name__ + ": " + type(error).__name__] += 1
            continue
        for row in rows:
            players, lineups = totals[
                "fouls_drawn" if FOULS_DRAWN in row["stat_key"] else "comparable"
            ]
            value = Decimal(str(row["stat_value"]))
            players[
                "{}|{}|{}".format(row["team_id"], row["player_id"], row["stat_key"])
            ] += value
            if "lineup_id" in row:
                key = (
                    row["team_id"],
                    row["lineup_id"],
                    row.get("opponent_lineup_id"),
                    row["stat_key"],
                )
                lineups[key] += value

    def text(number):
        number = number.normalize()
        return str(int(number)) if number == number.to_integral_value() else str(number)

    result = dict(errors=dict(errors))
    for part, (players, lineups) in totals.items():
        result[part] = dict(
            players={key: text(value) for key, value in sorted(players.items())},
            lineup_rows=len(lineups),
            lineups_sha256=digest(
                canonical(
                    sorted([list(map(str, key)), text(v)] for key, v in lineups.items())
                )
            ),
        )
    return result


def observations(loaded):
    from tools.parity.snapshot import snapshot
    from tools.parity.worker import credit_snapshot

    result = snapshot(loaded)
    for event, record in zip(loaded.events, result["events"]):
        record["kind"] = type(event).__name__
        record["codes"] = [event.event_type, getattr(event, "event_action_type", None)]
        # Keep each event's statistics comparable without storing every row.
        record["base_stats"] = digest(canonical(record["base_stats"]))
    return dict(
        snapshot=result, credits=credit_snapshot(loaded), stats=stat_totals(loaded)
    )


def load_v2(folder, game_id):
    from pbpstats.data_loader.stats_nba.possessions.file import (
        StatsNbaPossessionFileLoader,
    )
    from pbpstats.data_loader.stats_nba.possessions.loader import (
        StatsNbaPossessionLoader,
    )

    return StatsNbaPossessionLoader(
        game_id, StatsNbaPossessionFileLoader(str(folder / "v2"))
    )


def load_v3(folder, game_id, mode, live=None):
    from pbpstats.data_loader.stats_nba_v3 import (
        StatsNbaV3PossessionLoader,
        V3Context,
        V3JumpBallEvidence,
    )

    source = (folder / "v3" / mode / "{}.json".format(game_id)).read_bytes()
    facts = json.loads((folder / "v3/context/{}.json".format(game_id)).read_bytes())
    context = V3Context(
        game_id,
        tuple(facts["team_ids"]),
        {int(identity): value for identity, value in facts["roster"].items()},
        {},
        facts["source"],
        digest(source),
    )
    # The league's live play-by-play, an independent recording, not a V2 fact.
    path = live / "playbyplay_{}.json".format(game_id) if live else None
    evidence = (
        V3JumpBallEvidence(path.read_bytes(), str(path), digest(source))
        if path and path.exists()
        else None
    )
    return StatsNbaV3PossessionLoader(source, context, jump_balls=evidence)


def install_held_ball():
    """Install the adapter's held-ball extension, unchanged, into the original.

    The module is loaded from this checkout's file, so its imports bind to the
    original's classes in this worker. Candidates are swapped exactly as the
    adapter swaps them, before linking, including after order-repair rebuilds.
    """
    import importlib.util
    from pbpstats.data_loader.nba_enhanced_pbp_loader import NbaEnhancedPbpLoader

    spec = importlib.util.spec_from_file_location(
        "held_ball_extension", ROOT / "pbpstats/data_loader/stats_nba_v3/held_ball.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = NbaEnhancedPbpLoader._add_extra_attrs_to_all_events

    def add_extra_attrs_to_all_events(self):
        rows = {row["EVENTNUM"]: row for row in self.data}
        following = self.items[1:] + [None]
        self.items = [
            module.V3HeldBallJumpBall(rows[event.event_num], index)
            if module.is_candidate(event, following[index])
            else event
            for index, event in enumerate(self.items)
        ]
        original(self)

    NbaEnhancedPbpLoader._add_extra_attrs_to_all_events = add_extra_attrs_to_all_events
    return module.HELD_BALL_VERSION


def run_worker(args):
    from contextlib import redirect_stdout

    package = args.package.resolve()
    sys.dont_write_bytecode = True
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    socket.create_connection = offline
    sys.path.insert(0, str(package))
    import pbpstats

    if Path(pbpstats.__file__).resolve() != package / "pbpstats/__init__.py":
        raise RuntimeError("Wrong parser imported: " + str(pbpstats.__file__))
    sys.path.insert(1, str(ROOT))
    if args.held_ball:
        install_held_ball()
    games = json.loads(args.games.read_text(encoding="utf-8"))
    with gzip.open(args.output, "wt", encoding="utf-8") as output:
        for count, game_id in enumerate(games, 1):
            record = dict(game_id=game_id)
            try:
                with redirect_stdout(io.StringIO()):
                    loaded = (
                        load_v2(args.input, game_id)
                        if args.side == "v2"
                        else load_v3(args.input, game_id, args.clock, args.live)
                    )
            except Exception as error:
                record.update(
                    status="error",
                    error=type(error).__name__,
                    category=error_category(error),
                    message=str(error)[:400],
                )
            else:
                # A failure to observe a loaded game is a harness or adapter
                # defect, never a parser rejection.
                try:
                    record.update(status="ok", **observations(loaded))
                except Exception as error:
                    record.update(
                        status="observation_error",
                        error=type(error).__name__,
                        category="observation: " + type(error).__name__,
                        message=str(error)[:400],
                    )
            output.write(json.dumps(record) + "\n")
            if count % 100 == 0:
                print("{} {}/{}".format(args.side, count, len(games)), file=sys.stderr)


# ---------------------------------------------------------------- comparison


def masked_events(old, new):
    """Both event lists with the fouled player masked where V3 cannot know it.

    V3 never records the fouled player. Double fouls name both players in V3
    and stay compared, except a coach's double technical, which names none.
    """
    unknown = {
        e["event_id"]
        for e in new["snapshot"]["events"]
        if "Foul" in e.get("kind", "")
        and (e["codes"][1] not in (10, 16) or e["participants"]["player3_id"] is None)
    }

    def mask(events):
        return [
            (
                dict(e, participants=dict(e["participants"], player3_id="n/a"))
                if e["event_id"] in unknown
                else e
            )
            for e in events
        ]

    return mask(old["snapshot"]["events"]), mask(new["snapshot"]["events"])


def decision_view(record, events):
    """Time-blind, same-instant-order-blind decisions and attribution."""
    possessions = [
        dict(
            period=p["period"],
            offense=p["offense"],
            events=sorted(p["events"]),
            counted=p["counted"],
            start_type=p["start_type"],
            start_margin=p["start_margin"],
        )
        for p in record["snapshot"]["possessions"]
    ]
    events = {
        str(e["event_id"]): {
            k: v
            for k, v in e.items()
            if k not in ("previous", "next", "seconds", "base_stats")
        }
        for e in events
    }
    credits = dict(
        groups=[
            {k: v for k, v in group.items() if k != "end"}
            for group in record["credits"]["groups"]
        ],
        score=record["credits"]["score"],
        events=record["credits"]["events"],
    )
    return dict(possessions=possessions, events=events, credits=credits)


def generic_path(path):
    return re.sub(r"\[\d+\]", "[*]", re.sub(r"\.\d+(?=\.|$)", ".<event>", path))


def compare_game(old, new):
    from tools.parity.snapshot import first_difference

    row = dict(game_id=old["game_id"], v2=old["status"], v3=new["status"])
    if "observation_error" in (old["status"], new["status"]):
        for side, record in (("v2", old), ("v3", new)):
            if record["status"] != "ok":
                row[side + "_category"] = record["category"]
                row[side + "_message"] = record["message"]
        row["outcome"] = "observation_failed"
        return row
    if old["status"] != "ok" or new["status"] != "ok":
        for side, record in (("v2", old), ("v3", new)):
            if record["status"] != "ok":
                row[side + "_category"] = record["category"]
                row[side + "_message"] = record["message"]
        if old["status"] != "ok" and new["status"] != "ok":
            row["outcome"] = (
                "same_rejection"
                if old["category"] == new["category"]
                else "different_rejections"
            )
        else:
            row["outcome"] = (
                "v3_only_rejected" if old["status"] == "ok" else "v2_only_rejected"
            )
        return row

    def lineups(part):
        if old["stats"][part]["lineups_sha256"] == new["stats"][part]["lineups_sha256"]:
            return None
        return {
            "path": "$.lineup_totals",
            "expected": old["stats"][part]["lineup_rows"],
            "actual": new["stats"][part]["lineup_rows"],
        }

    old_events, new_events = masked_events(old, new)
    strict = dict(
        credits=first_difference(old["credits"], new["credits"]),
        possessions=first_difference(
            old["snapshot"]["possessions"], new["snapshot"]["possessions"]
        ),
        events=first_difference(old_events, new_events),
        player_stats=first_difference(
            old["stats"]["comparable"]["players"], new["stats"]["comparable"]["players"]
        ),
        lineup_stats=lineups("comparable"),
    )
    left, right = decision_view(old, old_events), decision_view(new, new_events)
    decisions = {
        level: first_difference(left[level], right[level])
        for level in ("credits", "possessions", "events")
    }
    row["strict_differences"] = {k: v for k, v in strict.items() if v}
    row["decision_differences"] = {k: v for k, v in decisions.items() if v}
    row["fouls_drawn_gap"] = bool(
        first_difference(
            old["stats"]["fouls_drawn"]["players"],
            new["stats"]["fouls_drawn"]["players"],
        )
        or lineups("fouls_drawn")
    )
    row["stat_errors"] = [old["stats"]["errors"], new["stats"]["errors"]]
    if not row["strict_differences"]:
        row["outcome"] = "identical"
    elif not row["decision_differences"]:
        row["outcome"] = "same_decisions"
    else:
        row["outcome"] = "different_decisions"
    return row


def read_records(path):
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def summarize(rows):
    summary = dict(outcomes=dict(Counter(r["outcome"] for r in rows)))
    summary["fouls_drawn_gap_games"] = sum(
        r.get("fouls_drawn_gap", False) for r in rows
    )
    summary["rejections"] = dict(
        Counter(
            (r["outcome"], r.get("v2_category"), r.get("v3_category"))
            for r in rows
            if "v2_category" in r or "v3_category" in r
        ).most_common()
    )
    summary["rejections"] = [
        dict(outcome=o, v2=a, v3=b, games=n)
        for (o, a, b), n in summary["rejections"].items()
    ]
    for kind in ("strict_differences", "decision_differences"):
        paths = Counter(
            level + " " + generic_path(diff["path"])
            for r in rows
            for level, diff in r.get(kind, {}).items()
        )
        summary[kind] = [dict(path=p, games=n) for p, n in paths.most_common(40)]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="nba-2024", help="nba-2024 or wnba-2025")
    parser.add_argument(
        "--output",
        type=Path,
        help="Default: .parity/season-differential-2024.json (NBA) or -<season>.json",
    )
    parser.add_argument("--games", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--limit", type=int, help="Compare only the first N games")
    parser.add_argument("--game", action="append", help="Compare only these game IDs")
    parser.add_argument("--keep", type=Path, help="Keep worker inputs/records here")
    parser.add_argument(
        "--held-ball",
        action="store_true",
        help="Also install the adapter's held-ball extension into the original on V2",
    )
    parser.add_argument(
        "--live",
        type=Path,
        help="Directory of recorded live play-by-play (playbyplay_<id>.json) given to the adapter as jump-ball evidence",
    )
    parser.add_argument("--worker", choices=("v2", "v3"), help=argparse.SUPPRESS)
    parser.add_argument("--package", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--clock", choices=MODES, help=argparse.SUPPRESS)
    parser.add_argument("--records", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        args.side, args.output = args.worker, args.records
        return run_worker(args)

    from pbpstats.data_loader.stats_nba_v3.held_ball import HELD_BALL_VERSION
    from tools.parity.paired_season import SEASONS, manifest, season
    from tools.parity.reference import prepare_reference

    if args.season not in SEASONS:
        parser.error("--season must be one of " + ", ".join(sorted(SEASONS)))
    if args.output is None:
        suffix = "2024" if args.season == "nba-2024" else args.season
        if args.held_ball:
            suffix += "-held-ball"
        if args.live:
            suffix += "-live"
        args.output = ROOT / ".parity/season-differential-{}.json".format(suffix)
    label = manifest(args.season)["season"]
    v2, v3, _ = season(args.season)
    game_ids = sorted(set(v2) & set(v3))
    if args.game:
        game_ids = [g for g in game_ids if g in set(args.game)]
    if args.limit:
        game_ids = game_ids[: args.limit]
    reference = prepare_reference()
    (ROOT / ".parity").mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="season-", dir=ROOT / ".parity"))
    try:
        unavailable, bound = prepare(folder, game_ids, v2, v3, label)
        (folder / "games-v2.json").write_text(json.dumps(game_ids), encoding="utf-8")
        v3_games = [g for g in game_ids if g not in unavailable]
        (folder / "games-v3.json").write_text(json.dumps(v3_games), encoding="utf-8")
        script = str(Path(__file__).resolve())
        jobs = {"v2": (reference, "v2", None, "games-v2.json")}
        for mode in MODES:
            jobs["v3_" + mode] = (ROOT, "v3", mode, "games-v3.json")
        processes = {}
        for name, (package, side, mode, games) in jobs.items():
            command = [
                sys.executable,
                "-I",
                "-B",
                script,
                "--worker",
                side,
                "--package",
                str(package),
                "--input",
                str(folder),
                "--games",
                str(folder / games),
                "--records",
                str(folder / (name + ".jsonl.gz")),
            ]
            if mode:
                command += ["--clock", mode]
            if side == "v2" and args.held_ball:
                command.append("--held-ball")
            if side == "v3" and args.live:
                command += ["--live", str(args.live.resolve())]
            log = open(folder / (name + ".log"), "w", encoding="utf-8")
            processes[name] = (
                subprocess.Popen(command, cwd=str(ROOT), stdout=log, stderr=log),
                log,
            )
        try:
            for name, (process, _) in processes.items():
                process.wait(timeout=7200)
                if process.returncode:
                    raise RuntimeError(
                        name
                        + " worker failed: "
                        + (folder / (name + ".log")).read_text(encoding="utf-8")[-4000:]
                    )
        finally:
            # Never leave a worker running against the folder removed below.
            for process, log in processes.values():
                if process.poll() is None:
                    process.kill()
                    process.wait()
                log.close()
        report = dict(
            schema_version=1,
            scope="Original V2 engine on the V2 export versus the V3 adapter on the paired V3 export; research comparison, not acceptance",
            season=label,
            evidence_manifest_sha256=digest((ROOT / SEASONS[args.season][0]).read_bytes()),
            shared_inputs=[
                "Shot coordinates for the original's shot-chart files come from the V3 export (xLegacy/yLegacy); the pinned evidence has no V2 shot chart."
            ],
            v2_extensions=[HELD_BALL_VERSION] if args.held_ball else [],
            # Recorded live play-by-play given to the adapter, by game: SHA-256.
            v3_live_evidence={
                path.stem.split("_")[-1]: digest(path.read_bytes())
                for path in sorted(args.live.glob("playbyplay_*.json"))
                if path.stem.split("_")[-1] in set(game_ids)
            }
            if args.live
            else {},
            implementation_hashes={
                p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
                for folder_ in (
                    ROOT / "pbpstats/data_loader/stats_nba_v3",
                    ROOT / "tools/parity",
                )
                for p in sorted(folder_.rglob("*.py"))
            },
            games=len(game_ids),
            v3_context_unavailable=unavailable,
            season_bound_substitutes=bound,
            modes={},
        )
        for mode in MODES:
            # Workers write games in the same order: stream both files together.
            new = read_records(folder / ("v3_" + mode + ".jsonl.gz"))
            rows = []
            for old in read_records(folder / "v2.jsonl.gz"):
                game_id = old["game_id"]
                if game_id in unavailable:
                    rows.append(
                        dict(
                            game_id=game_id,
                            v2=old["status"],
                            outcome="v3_context_unavailable",
                            **unavailable[game_id],
                        )
                    )
                    continue
                record = next(new)
                if record["game_id"] != game_id:
                    raise RuntimeError("Worker records are out of order: " + game_id)
                rows.append(compare_game(old, record))
            report["modes"][mode] = dict(summary=summarize(rows), games=rows)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(
            json.dumps(
                {mode: report["modes"][mode]["summary"]["outcomes"] for mode in MODES}
            )
        )
    finally:
        if args.keep:
            shutil.copytree(folder, args.keep, dirs_exist_ok=True)
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
