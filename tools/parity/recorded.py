"""Rebuild research context from recorded facts, without importing a prior parser.

Starter inference is conditional on the recorded substitution stream. It is not
proof that a provider recorded every substitution; minutes are checked separately.
Old parser fingerprints, readiness flags and inferred participants are not inputs.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
import json
import re

from pbpstats.data_loader.stats_nba_v3 import V3Context
from tools.parity.reference import digest
from tools.parity.participant_names import add_actor_aliases, add_unaccented_names
from tools.parity.recorded_supplements import add_recorded_aliases, live_foul_drawn_witnesses


VERSION = "recorded-context-v4"
CLOCK = re.compile(r"PT(\d+)M(\d+(?:\.\d+)?)S")
ON_COURT_FOULS = {
    "Personal",
    "Shooting",
    "Loose Ball",
    "Offensive",
    "Inbound",
    "Away From Play",
    "Clear Path",
    "Double Personal",
    "Flagrant Type 1",
    "Flagrant Type 2",
    "Offensive Charge",
    "Personal Block",
    "Personal Take",
    "Shooting Block",
    "Transition Take",
}


class EvidenceError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def require(condition, code, message, **details):
    if not condition:
        raise EvidenceError(code, message, **details)


def seconds(value):
    match = CLOCK.fullmatch(value) if isinstance(value, str) else None
    require(match is not None, "invalid_clock", "Invalid recorded clock", clock=value)
    require(Decimal(match[2]) < 60, "invalid_clock", "Seconds exceed 59", clock=value)
    return Decimal(match[1]) * 60 + Decimal(match[2])


def contained(root, relative):
    path = (root / relative.replace("\\", "/")).resolve()
    require(root in path.parents, "source_path_escape", "Source escapes selected root")
    return path


def read_capture(root, game):
    """Read only inventoried bytes, verifying every file before using any input."""
    capture = contained(root.resolve(), game["capture"])
    files = {}
    for relative, recorded in sorted(game["files"].items()):
        path = contained(capture, relative)
        require(
            path.is_file(),
            "source_missing",
            "Inventoried file is missing",
            path=relative,
        )
        data = path.read_bytes()
        actual = digest(data)
        require(
            actual == recorded["sha256"] == recorded["previous_sha256"],
            "source_changed",
            "Inventoried source hash changed",
            path=relative,
            expected=recorded["previous_sha256"],
            actual=actual,
        )
        files[relative.replace("\\", "/")] = data
    return files


@dataclass
class RecordedInput:
    source: bytes
    context: V3Context
    provenance: dict
    box: dict
    rows: list
    substitutions: dict


def prepare_recorded(game_id, files):
    """Derive starters, then compare saved starter assertions to the derivation."""
    pbp_path = "bundle/pbp/stats_v3_{}.json".format(game_id)
    box_path = "bundle/game_details/stats_v3_boxscore_{}.json".format(game_id)
    evidence_path = box_path.replace(".json", ".evidence.json")
    for path in (pbp_path, box_path, evidence_path):
        require(path in files, "missing_input", "Missing recorded input", path=path)
    source = files[pbp_path]
    game = json.loads(source)["game"]
    box = json.loads(files[box_path])["boxScoreTraditional"]
    evidence = json.loads(files[evidence_path])
    require(
        game.get("gameId") == box.get("gameId") == evidence.get("game_id") == game_id,
        "game_mismatch",
        "Recorded game identities disagree",
    )
    require(
        evidence.get("schema_version") == 1
        and evidence.get("boxscore_sha256") == digest(files[box_path])
        and evidence.get("scope") == "full_game"
        and evidence.get("roster_complete") is True
        and isinstance(evidence.get("source"), str)
        and evidence["source"].strip(),
        "roster_provenance",
        "Full recorded roster evidence is absent or stale",
    )
    teams = (box["homeTeamId"], box["awayTeamId"])
    require(len(set(teams)) == 2, "roster_identity", "Teams must be distinct")
    roster, opening = {}, {}
    for side, team in zip(("homeTeam", "awayTeam"), teams):
        require(
            box[side]["teamId"] == team,
            "roster_identity",
            "Box team identity disagrees",
        )
        opening[team] = []
        for player in box[side]["players"]:
            identity = player["personId"]
            require(
                type(identity) is int and identity > 0 and identity not in roster,
                "roster_identity",
                "Duplicate or invalid box player identity",
            )
            names = [player.get("familyName"), player.get("nameI")]
            if player.get("firstName") and player.get("familyName"):
                names.append(player["firstName"] + " " + player["familyName"])
            roster[identity] = {
                "team_id": team,
                "names": sorted({n for n in names if n}),
            }
            if player.get("position"):
                opening[team].append(identity)
    rows = game["actions"]
    require(isinstance(rows, list) and rows, "empty_pbp", "No recorded actions")
    # Only explicit ID-bound raw names augment the official box roster.
    for row in rows:
        identity = row.get("personId")
        if identity in roster:
            require(
                row.get("teamId") in (0, roster[identity]["team_id"]),
                "roster_identity",
                "Raw actor contradicts roster",
                action_number=row.get("actionNumber"),
            )
            for key in ("playerName", "playerNameI"):
                name = row.get(key)
                if (
                    isinstance(name, str)
                    and name.strip()
                    and name not in roster[identity]["names"]
                ):
                    roster[identity]["names"].append(name)
    alias_witnesses = add_actor_aliases(rows, roster, require)
    cross_recording_aliases = add_recorded_aliases(game_id, roster, require)
    live_witnesses = live_foul_drawn_witnesses(game_id, files, rows, roster, require)
    # Descriptions commonly omit accents from ID-bound official names.
    # Preserve originals and retain every match so collisions stay ambiguous.
    add_unaccented_names(roster)
    names = defaultdict(set)
    for identity, facts in roster.items():
        for name in facts["names"]:
            names[(facts["team_id"], name.casefold())].add(identity)

    def candidates_for(name, team):
        return set().union(
            *(
                names[t, name.strip().casefold()]
                for t in teams
                if team is None or t == team
            )
        )

    def resolve(name, team, index):
        candidates = candidates_for(name, team)
        require(
            len(candidates) == 1,
            "participant_evidence",
            "Recorded name is unresolved or ambiguous",
            name=name,
            team=team,
            source_index=index,
        )
        return next(iter(candidates))

    periods = defaultdict(list)
    for index, row in enumerate(rows):
        period = row.get("period")
        require(
            type(period) is int and period > 0,
            "period_completeness",
            "Invalid period",
            source_index=index,
        )
        periods[period].append((index, row))
    require(
        sorted(periods) == list(range(1, max(periods) + 1)) and max(periods) >= 4,
        "period_completeness",
        "Missing full-game periods",
    )
    require(
        [r["period"] for r in rows] == sorted(r["period"] for r in rows),
        "period_completeness",
        "Interleaved periods",
    )
    starters, witnesses, substitutions = {}, {}, {}
    deferred_tips, participant_resolutions = {}, []
    for period, items in periods.items():
        duration = Decimal(720 if period <= 4 else 300)
        starts = [
            i
            for i, r in items
            if (r["actionType"], r["subType"]) == ("period", "start")
        ]
        ends = [
            i for i, r in items if (r["actionType"], r["subType"]) == ("period", "end")
        ]
        require(
            len(starts) == len(ends) == 1
            and starts[0] < ends[0]
            and seconds(rows[starts[0]]["clock"]) == duration
            and seconds(rows[ends[0]]["clock"]) == 0,
            "period_completeness",
            "Missing or invalid period markers",
            period=period,
        )
        entered, seen = set(), {t: {} for t in teams}
        previous_clock = duration
        for index, row in items:
            clock = seconds(row["clock"])
            require(
                0 <= clock <= previous_clock,
                "clock_order",
                "Recorded clock moves backwards or exceeds period",
                source_index=index,
            )
            previous_clock = clock
            actor, team, kind, subtype = (
                row["personId"],
                row["teamId"],
                row["actionType"],
                row["subType"],
            )
            roles = []
            if index in live_witnesses:
                roles.append((live_witnesses[index]["player_id"], "live_foul_drawn"))
            if kind == "Substitution":
                require(
                    starts[0] < index < ends[0],
                    "interperiod_substitution",
                    "Substitution outside period markers requires separate review",
                    source_index=index,
                )
                match = re.fullmatch(r"SUB: (.+) FOR (.+)", row["description"])
                require(
                    match is not None and subtype == "",
                    "substitution_evidence",
                    "Malformed recorded substitution",
                    source_index=index,
                )
                outgoing, incoming = resolve(match[2], team, index), resolve(
                    match[1], team, index
                )
                require(
                    actor == outgoing and incoming != outgoing,
                    "substitution_evidence",
                    "Substitution contradicts explicit actor",
                    source_index=index,
                )
                substitutions[index] = (team, outgoing, incoming)
                roles.append((outgoing, "outgoing"))
                entered.add(incoming)
            elif (
                kind in ("Made Shot", "Missed Shot", "Rebound", "Turnover", "Jump Ball")
                or (kind == "Free Throw" and "Technical" not in subtype)
                or (kind == "Foul" and subtype in ON_COURT_FOULS)
            ):
                if actor in roster:
                    roles.append((actor, "actor"))
                assist = re.search(r"\(([^()]+?) \d+ AST\)", row["description"])
                if kind == "Made Shot" and assist:
                    roles.append((resolve(assist[1], team, index), "assister"))
                if kind == "Jump Ball":
                    match = re.fullmatch(
                        r"Jump Ball (.+) vs\. (.+): Tip to (.+)", row["description"]
                    )
                    if match:
                        opposing = next((t for t in teams if t != team), None)
                        roles.append(
                            (resolve(match[2], opposing, index), "opposing_jumper")
                        )
                        # Team-only recovery is not an individual on-court witness.
                        if match[3] != "Team":
                            candidates = candidates_for(match[3], None)
                            if len(candidates) > 1:
                                # Do not let an ambiguous tip supply its own starter
                                # evidence. Resolve only after independent starters.
                                deferred_tips[index] = (match[3], candidates)
                            else:
                                roles.append(
                                    (resolve(match[3], None, index), "tip_recipient")
                                )
            elif kind == "" and re.fullmatch(
                r".+ (?:STEAL \(\d+ STL\)|BLOCK \(\d+ BLK\))", row["description"]
            ):
                if actor in roster:
                    roles.append((actor, "secondary_actor"))
            for identity, role in roles:
                require(
                    starts[0] < index < ends[0],
                    "on_court_evidence",
                    "On-court witness outside period markers",
                    source_index=index,
                )
                if identity not in entered:
                    seen[roster[identity]["team_id"]].setdefault(
                        identity, {"source_index": index, "role": role}
                    )
        starters[period], witnesses[period] = {}, seen
        for team in teams:
            inferred = set(seen[team])
            if period == 1 and len(opening[team]) == 5:
                require(
                    inferred <= set(opening[team]),
                    "starter_conflict",
                    "Opening witnesses contradict box starters",
                    period=period,
                    team=team,
                )
                inferred = set(opening[team])
            require(
                len(inferred) == 5,
                "starter_evidence",
                "Need exactly five independently witnessed starters",
                period=period,
                team=team,
                players=sorted(inferred),
            )
            starters[period][team] = sorted(inferred)

        active = {p for players in starters[period].values() for p in players}
        for index, row in items:
            if index in substitutions:
                _, outgoing, incoming = substitutions[index]
                require(
                    outgoing in active and incoming not in active,
                    "raw_lineup_conflict",
                    "Raw substitution contradicts starters or earlier substitutions",
                    source_index=index,
                )
                active.remove(outgoing)
                active.add(incoming)
            if index in deferred_tips:
                name, candidates = deferred_tips[index]
                eligible = candidates & active
                require(
                    len(eligible) == 1,
                    "participant_evidence",
                    "Recorded name is unresolved or ambiguous on court",
                    name=name,
                    team=None,
                    source_index=index,
                    candidates=sorted(candidates),
                    on_court_candidates=sorted(eligible),
                )
                participant_resolutions.append(
                    dict(
                        source_index=index,
                        action_number=row["actionNumber"],
                        role="tip_recipient",
                        name=name,
                        candidates=sorted(candidates),
                        player_id=next(iter(eligible)),
                        on_court=sorted(active),
                        basis="recorded_starters_and_substitutions",
                    )
                )

    # Old lineup files are assertions to check, never a fallback for missing facts.
    checked = []
    for path, data in sorted(files.items()):
        if not path.endswith("/lineups.evidence.json"):
            continue
        saved = json.loads(data)
        require(
            saved.get("schema_version") == 1 and saved.get("game_id") == game_id,
            "saved_starter_conflict",
            "Saved lineup identity is invalid",
            path=path,
        )
        saved_periods = [p["period"] for p in saved["periods"]]
        require(
            len(saved_periods) == len(set(saved_periods))
            and set(saved_periods) == set(starters),
            "saved_starter_conflict",
            "Saved lineup periods differ",
            path=path,
        )
        for item in saved["periods"]:
            for side, team in zip(("home", "away"), teams):
                require(
                    sorted(item[side]) == starters[item["period"]][team],
                    "saved_starter_conflict",
                    "Saved starters disagree with independently reconstructed facts",
                    path=path,
                    period=item["period"],
                    team=team,
                )
        checked.append(path)
    provenance = {
        "version": VERSION,
        "source_hashes": {p: digest(data) for p, data in sorted(files.items())},
        "pbp_path": pbp_path,
        "boxscore_path": box_path,
        "actor_alias_witnesses": alias_witnesses,
        "cross_recording_alias_witnesses": cross_recording_aliases,
        "live_foul_drawn_witnesses": list(live_witnesses.values()),
        "participant_resolutions": participant_resolutions,
        "starter_witnesses": witnesses,
        "period_starters": starters,
        "saved_starters_checked": checked,
        "substitution_completeness": "conditional_on_recorded_stream",
        "prior_parser_outputs_used": False,
    }
    context = V3Context(
        game_id,
        teams,
        roster,
        starters,
        VERSION + ": " + digest(json.dumps(provenance, sort_keys=True).encode()),
        digest(source),
    )
    context.validate(source)
    return RecordedInput(source, context, provenance, box, rows, substitutions)


def reconcile(loaded, prepared):
    """Check independent raw substitution minutes, official minutes and scores."""
    from pbpstats.resources.enhanced_pbp import Substitution

    context, rows = prepared.context, prepared.rows
    expected = defaultdict(Decimal)
    for period, starters in context.period_starters.items():
        current = {team: set(players) for team, players in starters.items()}
        previous = Decimal(720 if period <= 4 else 300)
        for index, row in enumerate(rows):
            if row["period"] != period:
                continue
            clock = seconds(row["clock"])
            for players in current.values():
                for player in players:
                    expected[player] += previous - clock
            previous = clock
            if index in prepared.substitutions:
                team, outgoing, incoming = prepared.substitutions[index]
                require(
                    outgoing in current[team] and incoming not in current[team],
                    "raw_lineup_conflict",
                    "Raw substitution contradicts starters or earlier substitutions",
                    source_index=index,
                )
                current[team].remove(outgoing)
                current[team].add(incoming)
    actual = defaultdict(Decimal)
    for stat in loaded.base_stats:
        if stat["stat_key"] in ("SecondsPlayedOff", "SecondsPlayedDef"):
            actual[stat["player_id"]] += Decimal(str(stat["stat_value"]))
    minute_rows = []
    for side in ("homeTeam", "awayTeam"):
        for player in prepared.box[side]["players"]:
            identity = player["personId"]
            text = player["statistics"]["minutes"]
            require(
                isinstance(text, str)
                and (not text or re.fullmatch(r"\d+:\d{2}(?:\.\d+)?", text)),
                "official_minutes",
                "Unsupported official minute format",
                player_id=identity,
                minutes=text,
            )
            minutes, secs = text.split(":") if text else ("0", "0")
            # Box scores round some totals to MM:60, one more whole minute; the
            # one-second comparison below still applies.
            require(
                Decimal(secs) <= 60,
                "official_minutes",
                "Invalid official minute seconds",
                player_id=identity,
                minutes=text,
            )
            official = Decimal(minutes) * 60 + Decimal(secs)
            minute_rows.append(
                {
                    "player_id": identity,
                    "raw_seconds": str(expected[identity]),
                    "adapter_seconds": str(actual[identity]),
                    "official_seconds": str(official),
                }
            )
            require(
                abs(expected[identity] - actual[identity]) <= Decimal("0.000001"),
                "adapter_minutes",
                "Adapter minutes differ from raw substitutions",
                player_id=identity,
                minutes=minute_rows[-1],
            )
            require(
                abs(expected[identity] - official) <= 1,
                "official_minutes",
                "Player minutes differ by more than one second",
                player_id=identity,
                minutes=minute_rows[-1],
            )
    score = {
        prepared.box[s]["teamId"]: prepared.box[s]["statistics"]["points"]
        for s in ("homeTeam", "awayTeam")
    }
    require(
        dict(loaded.events[-1].score) == score,
        "official_score",
        "Adapter final score differs from official box",
        expected=score,
        actual=dict(loaded.events[-1].score),
    )
    require(
        sorted(i for e in loaded.events for i in e.v3_source_indices)
        == list(range(len(rows))),
        "source_coverage",
        "Source rows are duplicated or missing",
    )
    require(
        sum(isinstance(e, Substitution) for e in loaded.events)
        == len(prepared.substitutions),
        "substitution_coverage",
        "Substitutions are duplicated or missing",
    )
    return {
        "player_minutes": minute_rows,
        "score": score,
        "minute_tolerance_seconds": 1,
        "adapter_seconds_tolerance": "0.000001",
    }
