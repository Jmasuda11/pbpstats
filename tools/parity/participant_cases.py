"""Independent V2 IDs versus V3 names constrained by recorded lineups."""

import json

from tools.parity.reference import digest
from tools.parity.scenarios import AWAY, HOME, GAME, e, wrap, encode_v2, encode_v3


def catalog():
    for label, before, recipient, namesakes in (
        ("opening_tip", [], 12, [6, 12]),
        ("namesake_substituted_out", [e("sub", 650, HOME, 2, incoming=6)], 12, [2, 12]),
        (
            "recipient_substituted_in",
            [e("sub", 650, AWAY, 12, incoming=16)],
            16,
            [6, 16],
        ),
    ):
        yield dict(
            name=label,
            recipient=recipient,
            namesakes=namesakes,
            events=wrap(
                before
                + [
                    e(
                        "jump",
                        600,
                        HOME,
                        1,
                        opponent=11,
                        winner=recipient,
                        winner_team=AWAY,
                    ),
                    e("make", 580, AWAY, 11),
                    e("make", 560, HOME, 1),
                ]
            ),
        )


def v2_inputs(case):
    rows = encode_v2(case["events"])
    return rows, {
        r["EVENTNUM"]: (100, 120) for r in rows if r["EVENTMSGTYPE"] in (1, 2)
    }


def v3_inputs(case):
    rows = encode_v3(case["events"])
    for row in rows:
        if row["actionType"] == "Jump Ball":
            row["description"] = "Jump Ball Player1 vs. Player11: Tip to Shared"
        if row["actionType"] in ("Made Shot", "Missed Shot"):
            row.update(xLegacy=100, yLegacy=120)
    roster = {
        p: dict(
            team_id=t,
            names=["Player{}".format(p)]
            + (["Shared"] if p in case["namesakes"] else []),
        )
        for t, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for p in players
    }
    return rows, roster


def load_v3(rows, roster):
    from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader, V3Context

    source = json.dumps(dict(game=dict(gameId=GAME, actions=rows))).encode()
    context = V3Context(
        GAME,
        (HOME, AWAY),
        roster,
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Independent synthetic starter/name facts",
        digest(source),
    )
    return StatsNbaV3PossessionLoader(
        source, context, validate_source_order=False, validate_possessions=False
    )
