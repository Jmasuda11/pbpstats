"""Controlled shot facts encoded independently for original V2 and candidate V3.

Action codes come from pinned recording observations, never the adapter's table.
Direct original-event statistics here are research observations on complete shot
inputs; this suite does not enable the candidate's aggregate statistics API.
"""

import json

from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, e, encode_v2, encode_v3, wrap
from tools.parity.snapshot import scalar, snapshot, stats_rows


def vocabulary():
    return json.loads((ROOT / "tests/parity/shot-vocabulary.json").read_bytes())


def catalog():
    for mapping in vocabulary()["mappings"]:
        for outcome in ("made", "assisted", "missed", "blocked"):
            made = outcome in ("made", "assisted")
            events = [e("make" if made else "miss", 600)]
            if not made:
                events.append(e("rebound", 599, AWAY, 11))
            events.append(e("make", 580, AWAY, 11))
            yield {
                "name": mapping["subtype"] + "/" + outcome,
                "subtype": mapping["subtype"],
                "v2_action_type": mapping["v2_action_type"],
                "outcome": outcome,
                "events": wrap(events),
                "location": (10, 15),
            }


def v2_inputs(case):
    rows = encode_v2(case["events"])
    shot = rows[1]
    shot["EVENTMSGACTIONTYPE"] = case["v2_action_type"]
    shot["NEUTRALDESCRIPTION"] = (
        ("MISS " if case["outcome"] in ("missed", "blocked") else "")
        + "Player1 2' "
        + case["subtype"]
    )
    if case["outcome"] == "assisted":
        shot["PLAYER2_ID"] = 2
        shot["NEUTRALDESCRIPTION"] += " (2 PTS) (Player2 1 AST)"
    if case["outcome"] == "blocked":
        shot["PLAYER3_ID"] = 11
    # Independently supplied shot-chart facts for the original loader path.
    coordinates = {
        row["EVENTNUM"]: case["location"] if row["EVENTNUM"] == 2 else (100, 120)
        for row in rows
        if row["EVENTMSGTYPE"] in (1, 2)
    }
    return rows, coordinates


def v3_inputs(case):
    rows = encode_v3(case["events"])
    shot = rows[1]
    shot["subType"] = case["subtype"]
    shot["description"] = (
        ("MISS " if case["outcome"] in ("missed", "blocked") else "")
        + "Player1 2' "
        + case["subtype"]
    )
    if case["outcome"] == "assisted":
        shot["description"] += " (2 PTS) (Player2 1 AST)"
    for row in rows:
        if row["actionType"] in ("Made Shot", "Missed Shot"):
            row["xLegacy"], row["yLegacy"] = (
                case["location"] if row["actionNumber"] == 2 else (100, 120)
            )
    if case["outcome"] == "blocked":
        # A separately recorded V3 row, not a participant field copied from V2.
        rows.insert(
            2,
            {
                "actionNumber": 2,
                "actionId": 99,
                "period": 1,
                "clock": "PT10M00S",
                "actionType": "",
                "subType": "",
                "personId": 11,
                "teamId": AWAY,
                "description": "Player11 BLOCK (1 BLK)",
            },
        )
    return rows


def shot_snapshot(loaded):
    result = snapshot(loaded)
    # No attempt()/unavailable placeholders: all these shot facts must evaluate.
    result["shot_details"] = [
        scalar(
            {
                "event_id": event.event_num,
                "event_action_type": event.event_action_type,
                "locX": event.locX,
                "locY": event.locY,
                "distance": event.distance,
                "shot_type": event.shot_type,
                "is_corner_3": event.is_corner_3,
                "is_heave": event.is_heave,
                "shot_data": event.shot_data,
                "event_stats": stats_rows(event.event_stats),
            }
        )
        for event in loaded.events
        if event.event_type in (1, 2)
    ]
    return result
