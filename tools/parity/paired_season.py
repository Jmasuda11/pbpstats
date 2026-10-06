"""Pair the pinned 2024-25 PlayByPlayV2 and V3 exports event by event.

The pairing records facts only: event correspondence, the V2 code recorded for
each V3 label, clocks, actors, same-instant ordering and information that one
feed lacks. The candidate decoder is compared against those facts, never
changed here. Archives are read in memory; nothing is extracted to disk.
"""

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path
import re
import tarfile

from tools.parity.reference import ROOT, digest, prepare_reference

MANIFEST = "tests/parity/paired-season-evidence.json"
EXPECTED = "tests/parity/paired-season-2024.json"
CLOCK = re.compile(r"PT(\d+)M(\d+(?:\.\d+)?)S")
JUMP_BALL = re.compile(r"Jump Ball (?:\(CC\) )?(.+?) vs\. (.+?): Tip to (.*)")


@lru_cache(maxsize=1)
def manifest():
    return json.loads((ROOT / MANIFEST).read_bytes())


def git_blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def read_rows(spec):
    raw = (ROOT / spec["path"]).read_bytes()
    if (len(raw), digest(raw), git_blob_sha1(raw)) != (
        spec["bytes"],
        spec["sha256"],
        spec["git_blob_sha1"],
    ):
        raise ValueError("Pinned export changed: " + spec["path"])
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
        if archive.getnames() != [spec["member"]]:
            raise ValueError("Unexpected export members: " + spec["path"])
        # Read the named member in memory; never extract archive paths.
        data = archive.extractfile(spec["member"]).read()
    if digest(data) != spec["member_sha256"]:
        raise ValueError("Pinned export member changed: " + spec["member"])
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def v3_action(row, integers):
    """Typed action from export text; the only repair strips export padding."""
    action = {}
    for key, value in row.items():
        if key == "gameId":
            continue
        if key in integers:
            action[key] = int(value)
        elif key in ("actionType", "subType"):
            action[key] = value.strip()
        else:
            action[key] = value
    return action


@lru_cache(maxsize=1)
def season():
    """Return ({game_id: v2 rows}, {game_id: typed v3 actions}, padding counts)."""
    evidence = manifest()
    for path, expected in evidence["provenance_files"].items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise ValueError("Provenance file changed: " + path)
    integers = set(evidence["normalization"]["v3_integers"])
    v2, v3, padding = defaultdict(list), defaultdict(list), Counter()
    for row in read_rows(evidence["archives"]["v2"]):
        v2[row["GAME_ID"].zfill(10)].append(row)
    for row in read_rows(evidence["archives"]["v3"]):
        action = v3_action(row, integers)
        if (row["actionType"], row["subType"]) != (
            action["actionType"],
            action["subType"],
        ):
            padding[action["actionType"] + "|" + action["subType"]] += 1
        v3[row["gameId"].zfill(10)].append(action)
    return dict(v2), dict(v3), dict(padding)


def fidelity_witness():
    """Compare one exported game with its separately recorded JSON response."""
    witness = manifest()["fidelity_witness"]
    raw = (prepare_reference(witness["reference"]) / witness["path"]).read_bytes()
    if digest(raw) != witness["sha256"]:
        raise ValueError("Fidelity witness changed")
    recorded = json.loads(raw)["game"]
    exported = season()[1][witness["game_id"]]
    return recorded["gameId"] == witness["game_id"] and recorded["actions"] == exported


def seconds(clock):
    match = CLOCK.fullmatch(clock)
    return int(match[1]) * 60 + Decimal(match[2])


def v2_seconds(text):
    minutes, secs = text.split(":")
    return int(minutes) * 60 + int(secs)


def number(text):
    return int(text) if text else 0


def clock_relation(exact, whole):
    if exact == whole:
        return "equal"
    if whole == math.floor(exact):
        return "v2_floor_of_fractional_v3"
    return "other"


def lcs(first, second):
    table = [[0] * (len(second) + 1) for _ in range(len(first) + 1)]
    for i, a in enumerate(first):
        for j, b in enumerate(second):
            table[i + 1][j + 1] = (
                table[i][j] + 1 if a == b else max(table[i][j + 1], table[i + 1][j])
            )
    return table[-1][-1]


def instants(sequence, actions):
    """Collapse an event order into consecutive same-instant groups."""
    runs = []
    for event in sequence:
        key = (actions[event]["period"], actions[event]["clock"])
        if runs and runs[-1][0] == key:
            runs[-1][1].append(event)
        else:
            runs.append((key, [event]))
    return runs


def held_ball(actions, index):
    """Jump ball followed by a lost-ball turnover and steal between its jumpers."""
    match = JUMP_BALL.fullmatch(actions[index]["description"].strip())
    following = index + 1
    while following < len(actions) and actions[following]["actionType"] in (
        "Substitution",
        "Timeout",
        "",
    ):
        following += 1
    if not match or following + 1 >= len(actions):
        return None
    turnover, steal = actions[following], actions[following + 1]
    if (turnover["actionType"], turnover["subType"]) != ("Turnover", "Lost Ball") or (
        steal["actionType"] or " STEAL " not in steal["description"] + " "
    ):
        return None
    names = {
        turnover["description"].split(" Lost Ball")[0].strip(),
        steal["description"].split(" STEAL")[0].strip(),
    }
    return turnover if names == {match[1].strip(), match[2].strip()} else None


def pair(v2, v3):
    """Return (pinned facts, illustrative details) for the whole season."""
    # Zero entries keep pinned facts explicit when a category never occurs.
    join, codes, roles = Counter(), defaultdict(Counter), Counter()
    clocks = Counter(equal=0, v2_floor_of_fractional_v3=0, other=0)
    order = Counter(games_with_cross_instant_difference=0)
    reordered_kinds, gaps = Counter(), Counter()
    held = Counter(v2_lost_ball_turnover_with_stealer=0, v2_other=0)
    duplicates, details = [], defaultdict(list)
    held_games = set()
    for game_id in sorted(set(v2) | set(v3)):
        old, new = v2.get(game_id, []), v3.get(game_id, [])
        join["v2_rows"] += len(old)
        join["v3_rows"] += len(new)
        events, sequence = {}, []
        for row in old:
            event = int(row["EVENTNUM"])
            if event in events:
                duplicates.append(
                    dict(
                        game_id=game_id, event_num=event, identical=events[event] == row
                    )
                )
                continue
            events[event] = row
            sequence.append(event)
        primary = {a["actionNumber"]: a for a in new if a["actionType"]}
        secondary = defaultdict(list)
        for action in new:
            if not action["actionType"]:
                secondary[action["actionNumber"]].append(action)
        join["v2_events"] += len(events)
        join["v3_primary"] += len(primary)
        join["v3_secondary"] += sum(len(rows) for rows in secondary.values())
        join["v2_only"] += len(set(events) - set(primary))
        join["v3_only"] += len(set(primary) - set(events))
        join["games_exact_event_set"] += set(events) == set(primary)
        for number_, action in primary.items():
            if number_ not in events:
                continue
            row = events[number_]
            key = (action["actionType"], action["subType"])
            codes[key][(int(row["EVENTMSGTYPE"]), int(row["EVENTMSGACTIONTYPE"]))] += 1
            clocks[
                clock_relation(
                    seconds(action["clock"]), v2_seconds(row["PCTIMESTRING"])
                )
            ] += 1
            join["periods_equal"] += action["period"] == int(row["PERIOD"])
            join["actors_equal"] += action["personId"] == number(row["PLAYER1_ID"])
            join["actor_teams_equal"] += action["teamId"] == number(
                row["PLAYER1_TEAM_ID"]
            )
            for extra in secondary.get(number_, []):
                if " STEAL (" in extra["description"]:
                    roles["steal_matches_v2_player2"] += extra["personId"] == number(
                        row["PLAYER2_ID"]
                    )
                    roles["steals"] += 1
                elif " BLOCK (" in extra["description"]:
                    roles["block_matches_v2_player3"] += extra["personId"] == number(
                        row["PLAYER3_ID"]
                    )
                    roles["blocks"] += 1
            if row["EVENTMSGTYPE"] == "6":
                gaps["v2_fouls"] += 1
                gaps["v2_fouls_with_fouled_player"] += number(row["PLAYER2_ID"]) > 0
            if (
                action["actionType"] == "Jump Ball"
                and not action["description"].strip()
            ):
                gaps["v3_blank_jump_balls"] += 1
                gaps["with_v2_opposing_jumper"] += number(row["PLAYER2_ID"]) > 0
                gaps["with_v2_recipient_or_team"] += number(row["PLAYER3_ID"]) > 0
                if len(details["blank_jump_balls"]) < 5:
                    details["blank_jump_balls"].append(
                        dict(
                            game_id=game_id,
                            event_num=number_,
                            v2=[
                                row[k]
                                for k in ("PLAYER1_ID", "PLAYER2_ID", "PLAYER3_ID")
                            ],
                        )
                    )
        new_sequence = [a["actionNumber"] for a in new if a["actionType"]]
        if sequence == new_sequence:
            order["games_identical"] += 1
        else:
            order["games_different"] += 1
            old_runs = instants(sequence, primary)
            new_runs = instants(new_sequence, primary)
            if [(k, sorted(e)) for k, e in old_runs] != [
                (k, sorted(e)) for k, e in new_runs
            ]:
                order["games_with_cross_instant_difference"] += 1
            else:
                for (key, first), (_, second) in zip(old_runs, new_runs):
                    if first == second:
                        continue
                    order["instants_reordered"] += 1
                    order["events_in_reordered_instants"] += len(first)
                    order["events_moved"] += len(first) - lcs(first, second)
                    for event in first:
                        action = primary[event]
                        reordered_kinds[
                            action["actionType"] + "|" + action["subType"]
                        ] += 1
                    if len(details["reordered_instants"]) < 5:
                        details["reordered_instants"].append(
                            dict(
                                game_id=game_id,
                                period=key[0],
                                clock=key[1],
                                v2=first,
                                v3=second,
                            )
                        )
        for index, action in enumerate(new):
            if action["actionType"] != "Jump Ball":
                continue
            turnover = held_ball(new, index)
            if turnover is None:
                continue
            held["occurrences"] += 1
            held[
                "same_clock" if turnover["clock"] == action["clock"] else "later_clock"
            ] += 1
            held_games.add(game_id)
            row = events.get(turnover["actionNumber"], {})
            held[
                (
                    "v2_lost_ball_turnover_with_stealer"
                    if (row.get("EVENTMSGTYPE"), row.get("EVENTMSGACTIONTYPE"))
                    == ("5", "2")
                    and number(row.get("PLAYER2_ID")) > 0
                    else "v2_other"
                )
            ] += 1
            if len(details["held_balls"]) < 5:
                details["held_balls"].append(
                    dict(
                        game_id=game_id,
                        jump_ball=[
                            action["actionNumber"],
                            action["clock"],
                            action["description"],
                        ],
                        turnover=[
                            turnover["actionNumber"],
                            turnover["clock"],
                            turnover["description"],
                        ],
                    )
                )
    held["games"] = len(held_games)
    facts = {
        "games": len(set(v2) | set(v3)),
        "games_in_both": len(set(v2) & set(v3)),
        "join": dict(sorted(join.items())),
        "v2_duplicate_rows": duplicates,
        "clocks": dict(sorted(clocks.items())),
        "secondary_roles": dict(sorted(roles.items())),
        "codes": [
            dict(
                actionType=kind,
                subType=subtype,
                v2=[
                    dict(event_type=t, action_type=a, events=n)
                    for (t, a), n in sorted(counts.items())
                ],
            )
            for (kind, subtype), counts in sorted(codes.items())
        ],
        "order": dict(sorted(order.items())),
        "reordered_instant_kinds": dict(sorted(reordered_kinds.items())),
        "v3_information_gaps": dict(sorted(gaps.items())),
        "held_ball_turnovers": dict(sorted(held.items())),
    }
    return facts, dict(details)


def decoder_comparison(v3, facts):
    """Decode one real sample per V3 label with the candidate's own decoder."""
    import pbpstats
    from pbpstats.data_loader.stats_nba_v3.decoder import (
        DecodedV3,
        V3Context,
        V3DecodeError,
    )
    from tools.parity.participant_names import roster_from_actors
    from tools.parity.recorded import require

    if Path(pbpstats.__file__).resolve() != ROOT / "pbpstats/__init__.py":
        raise ValueError("Wrong pbpstats package imported")
    wanted = {(c["actionType"], c["subType"]): c["v2"] for c in facts["codes"]}
    samples = defaultdict(list)
    for game_id, actions in sorted(v3.items()):
        for index, action in enumerate(actions):
            key = (action["actionType"], action["subType"])
            if key in wanted and len(samples[key]) < 25:
                samples[key].append((game_id, index))
    result = []
    for key, expected in sorted(wanted.items()):
        outcome = None
        for game_id, index in samples[key]:
            actions = v3[game_id]
            group = [
                a
                for a in actions
                if a["actionNumber"] == actions[index]["actionNumber"]
            ]
            teams = sorted({a["teamId"] for a in actions if a["teamId"]})
            source = json.dumps(
                {"game": {"gameId": game_id, "actions": group}}
            ).encode()
            try:
                context = V3Context(
                    game_id,
                    tuple(teams),
                    roster_from_actors(actions, teams, require),
                    {},
                    "Paired-season label sample; roster from the same game's V3 actors",
                    digest(source),
                )
                projected = DecodedV3(source, context).projected[0]
            except (V3DecodeError, KeyError, ValueError) as error:
                outcome = outcome or dict(
                    status="rejected", reason=str(error).split(": ", 1)[-1]
                )
                continue
            outcome = dict(
                status="decoded",
                event_type=projected["EVENTMSGTYPE"],
                action_type=projected["EVENTMSGACTIONTYPE"],
            )
            break
        recorded = [(e["event_type"], e["action_type"]) for e in expected]
        if outcome["status"] == "rejected":
            outcome["verdict"] = "rejected"
        elif recorded == [(outcome["event_type"], outcome["action_type"])]:
            outcome["verdict"] = "matches"
        else:
            outcome["verdict"] = "differs"
        result.append(
            dict(
                actionType=key[0],
                subType=key[1],
                v2=recorded,
                events=sum(e["events"] for e in expected),
                decoder=outcome,
            )
        )
    return result


def report():
    v2, v3, padding = season()
    facts, details = pair(v2, v3)
    facts["export_padding"] = dict(sorted(padding.items()))
    facts["fidelity_witness_matches"] = fidelity_witness()
    return {
        "schema_version": 1,
        "scope": "paired 2024-25 export facts; not an adapter acceptance result",
        "evidence_manifest_sha256": digest((ROOT / MANIFEST).read_bytes()),
        "facts": facts,
        "decoder_comparison": decoder_comparison(v3, facts),
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".parity/paired-season-2024.json"
    )
    parser.add_argument(
        "--write-expected",
        action="store_true",
        help="Explicitly replace the pinned facts in " + EXPECTED,
    )
    args = parser.parse_args()
    result = report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.write_expected:
        (ROOT / EXPECTED).write_text(
            json.dumps(result["facts"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    verdicts = Counter(c["decoder"]["verdict"] for c in result["decoder_comparison"])
    print(json.dumps(dict(join=result["facts"]["join"], decoder=dict(verdicts))))


if __name__ == "__main__":
    main()
