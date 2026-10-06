"""Candidate synthetic input uses no original-V2 outputs as decoding evidence."""

import hashlib
import json

from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader, V3Context
from tools.parity.scenarios import AWAY, HOME, GAME, encode_v3


def load_synthetic(events):
    return load_synthetic_rows(encode_v3(events))


def load_synthetic_rows(rows):
    source = json.dumps({"game": {"gameId": GAME, "actions": rows}}).encode()
    roster = {
        player: {"team_id": team, "names": ["Player{}".format(player)]}
        for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for player in players
    }
    context = V3Context(
        GAME,
        (HOME, AWAY),
        roster,
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Independent synthetic roster/starters",
        hashlib.sha256(source).hexdigest(),
    )
    return StatsNbaV3PossessionLoader(
        source, context, validate_possessions=False, validate_source_order=False
    )


def load_paired(data):
    """Use reviewed V3 roster/starters; never read paired V2 participant fields."""
    source = (data / "pbp/stats_v3_0021900001.json").read_bytes()
    payload = json.loads(source)
    box = json.loads(
        (data / "game_details/stats_v3_boxscore_0021900001.json").read_bytes()
    )["boxScoreTraditional"]
    lineups = json.loads((data / "v3/lineups_0021900001.evidence.json").read_bytes())
    roster = {}
    for side in ("homeTeam", "awayTeam"):
        team = box[side]["teamId"]
        for player in box[side]["players"]:
            roster[player["personId"]] = {
                "team_id": team,
                "names": [
                    player["familyName"],
                    player["firstName"] + " " + player["familyName"],
                ],
            }
    for row in payload["game"]["actions"]:
        player = roster.get(row["personId"])
        if player and row["teamId"] == player["team_id"]:
            for key in ("playerName", "playerNameI"):
                if row.get(key) and row[key] not in player["names"]:
                    player["names"].append(row[key])
    teams = (box["homeTeamId"], box["awayTeamId"])
    starters = {
        p["period"]: {teams[0]: p["home"], teams[1]: p["away"]}
        for p in lineups["periods"]
    }
    context = V3Context(
        GAME,
        teams,
        roster,
        starters,
        "Reviewed NBA.com roster and per-period starters; explicit ID-bound V3 names",
        hashlib.sha256(source).hexdigest(),
    )
    return StatsNbaV3PossessionLoader(source, context)
