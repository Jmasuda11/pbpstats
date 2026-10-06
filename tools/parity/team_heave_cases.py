"""Extension checks against controlled V2 team-miss analogues, not recordings.

The analogue verifies shared possession/rebound behavior. It cannot establish
historical V2 parity for a new league event. Extension statistics are tested
separately, including the absence of any individual shooting debit.
"""

import hashlib
import itertools
import json

from tools.parity.scenarios import HOME, AWAY, e, wrap, encode_v2, encode_v3
from tools.parity.snapshot import snapshot, stats_rows


GAME = "0022500001"


def catalog():
    for start, period, rebound, blocked, substitute in itertools.product(
        ("2", "2.1", "5"), (1, 4, 5),
        ("placeholder", "team_live", "offensive", "defensive"),
        (False, True), (False, True),
    ):
        events = [e("make", 240 if period > 4 else 600, HOME, 1),
                  e("make", start, AWAY, 11)]
        if substitute:
            events.append(e("sub", start, HOME, 2, incoming=6))
        events.append(e("miss", "0.2", HOME, 0, value=3))
        team, player, clock = {
            "placeholder": (HOME, 0, "0.2"),
            "team_live": (HOME, 0, "0.1"),
            "offensive": (HOME, 1, "0.1"),
            "defensive": (AWAY, 12, "0.1"),
        }[rebound]
        events.append(e("rebound", clock, team, player))
        events = wrap(events)
        for event in events:
            event["period"] = period
        events[0]["clock"] = "300" if period > 4 else "720"
        yield dict(
            name=f"heave_{start}_p{period}_{rebound}_block{int(blocked)}_sub{int(substitute)}",
            events=events, start=start, period=period, rebound=rebound,
            blocked=blocked, substitute=substitute,
        )


def v2_inputs(case):
    rows = encode_v2(case["events"])
    for row in rows:
        row["GAME_ID"] = GAME
        if row["EVENTMSGTYPE"] == 2:
            row["NEUTRALDESCRIPTION"] = "MISS Team 3PT Jump Shot"
            if case["blocked"]:
                row["PLAYER3_ID"] = 11
    return rows


def v3_inputs(case):
    rows = encode_v3(case["events"])
    for row in rows:
        if row["actionType"] == "Missed Shot":
            row.update(
                actionType="Heave", subType="Team Field Goal Attempt",
                description="HOME Heave", personId=0, teamId=0, location="h",
                isFieldGoal=0, shotValue=0, shotResult="",
                shotDistance=0, xLegacy=0, yLegacy=0,
            )
            if case["blocked"]:
                block = dict(row, actionId=99, actionType="", subType="",
                             personId=0, teamId=0, location="v",
                             description="Player11 BLOCK (1 BLK)")
    if case["blocked"]:
        index = next(i for i, r in enumerate(rows) if r["actionType"] == "Heave")
        rows.insert(index + 1, block)
    return rows


def load_v3(rows, game_id=GAME):
    from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader, V3Context

    source = json.dumps({"game": {"gameId": game_id, "actions": rows}}).encode()
    roster = {
        p: {"team_id": team, "names": [f"Player{p}"]}
        for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for p in players
    }
    context = V3Context(
        game_id, (HOME, AWAY), roster,
        {rows[0]["period"]: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Independent controlled team-heave context", hashlib.sha256(source).hexdigest(),
    )
    return StatsNbaV3PossessionLoader(source, context)


def behavior_snapshot(loaded):
    result = snapshot(loaded)
    # All rebound statistics include retained shooter-team, blocker and rebounder
    # attribution. Shot-only extension metadata/counters are tested separately.
    result["rebound_stats"] = [
        {"event_id": event.event_num, "stats": stats_rows(event.event_stats)}
        for event in loaded.events if event.event_type == 4
    ]
    return result
