"""V3 source facts -> original event constructor fields, with source lineage.

This module contains no possession boundary, foul association or rebound rules.
The projection is an internal constructor adapter, never a historical V2 feed.
"""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re


class V3DecodeError(ValueError):
    pass


@dataclass
class V3Context:
    game_id: str
    team_ids: tuple
    roster: dict
    period_starters: dict
    source: str
    pbp_sha256: str

    def validate(self, source_bytes):
        if not isinstance(self.source, str) or not self.source.strip():
            raise V3DecodeError("Context requires source provenance")
        if hashlib.sha256(source_bytes).hexdigest() != self.pbp_sha256:
            raise V3DecodeError("Context does not match the raw PBP hash")
        if not isinstance(self.game_id, str) or not re.fullmatch(
            r"00\d{8}", self.game_id
        ):
            raise V3DecodeError(
                "Initial compatibility adapter supports NBA game IDs only"
            )
        if (
            len(self.team_ids) != 2
            or len(set(self.team_ids)) != 2
            or any(type(t) is not int or t <= 0 for t in self.team_ids)
        ):
            raise V3DecodeError("Exactly two distinct team IDs are required")
        for player_id, player in self.roster.items():
            if (
                type(player_id) is not int
                or player_id <= 0
                or player["team_id"] not in self.team_ids
            ):
                raise V3DecodeError("Invalid roster identity")
            if not player.get("names") or any(
                not isinstance(n, str) or not n.strip() for n in player["names"]
            ):
                raise V3DecodeError("Roster names must be nonempty strings")
        for period, teams in self.period_starters.items():
            if (
                type(period) is not int
                or period <= 0
                or set(teams) != set(self.team_ids)
            ):
                raise V3DecodeError("Invalid period starter context")
            for team, players in teams.items():
                if len(players) != 5 or len(set(players)) != 5:
                    raise V3DecodeError(
                        "Period starters require five distinct players per team"
                    )
                if any(
                    player not in self.roster or self.roster[player]["team_id"] != team
                    for player in players
                ):
                    raise V3DecodeError("Starter not in the recorded team roster")


# Non-shot codes are the V2 codes recorded for the same events in the paired
# 2024-25 exports (tests/parity/paired-season-2024.json). Inbound, Personal
# Block and Shooting Block are unobserved there; they keep the original's own
# named codes. A blank subtype is V2 code 0, e.g. the original's no-turnover.
FOULS = {
    "": 0,
    "Personal": 1,
    "Shooting": 2,
    "Loose Ball": 3,
    "Offensive": 4,
    "Inbound": 5,
    "Away From Play": 6,
    "Clear Path": 9,
    "Double Personal": 10,
    "Technical": 11,
    "Non-Unsportsmanlike Technical": 12,
    "Hanging Technical": 13,
    "Flagrant Type 1": 14,
    "Flagrant Type 2": 15,
    "Double Technical": 16,
    "Defense 3 Second": 17,
    "Delay Technical": 18,
    "Excess Timeout Technical": 25,
    "Offensive Charge": 26,
    "Personal Block": 27,
    "Personal Take": 28,
    "Shooting Block": 29,
    "Too Many Players Technical": 30,
    "Transition Take": 31,
    "Flopping": 32,
    "Bench": 33,
}
TURNOVERS = {
    "": 0,
    "Bad Pass": 1,
    "Lost Ball": 2,
    "Traveling": 4,
    "Double Dribble": 6,
    "Discontinue Dribble": 7,
    "3 Second Violation": 8,
    "5 Second Violation": 9,
    "8 Second Violation": 10,
    "Shot Clock Turnover": 11,
    "Inbound Turnover": 12,
    "Backcourt Turnover": 13,
    "Offensive Goaltending": 15,
    "Lane Violation": 17,
    "Jump Ball Violation": 18,
    "Kicked Ball Violation": 19,
    "Illegal Assist Turnover": 20,
    "Palming Turnover": 21,
    "10 Second Violaton": 24,
    "Punched Ball Turnover": 33,
    "Basket from Below Turnover": 35,
    "Illegal Screen Turnover": 36,
    "Offensive Foul Turnover": 37,
    "Step Out of Bounds Turnover": 39,
    "Out of Bounds Lost Ball Turnover": 40,
    "Excess Timeout Turnover": 42,
    "Too Many Players Turnover": 44,
    "Out of Bounds - Bad Pass Turnover": 45,
}
VIOLATIONS = {
    "Delay Of Game": 1,
    "Defensive Goaltending": 2,
    "Lane": 3,
    "Jump Ball": 4,
    "Kicked Ball": 5,
    "Double Lane": 6,
}
REBOUNDS = {"Unknown": 0, "Normal Rebound": 1}
TIMEOUTS = {"Regular": 1, "Coach Challenge": 7}
JUMP_BALLS = {"": 0, "Coach Challenge": 1}
REPLAYS = {
    "Support Ruling": 0,
    "Overturn Ruling": 1,
    "Altercation Ruling": 2,
    "Ruling Stands": 3,
    "Coach Challenge Support Ruling": 4,
    "Coach Challenge Overturn Ruling": 5,
    "Coach Challenge Ruling Stands": 6,
    "Replay Center": 7,
}
EJECTIONS = {"Other": 4}
# Technicals and ejections can name people outside the player roster: coaches
# (no team in either feed) and inactive players (with their team). V3 records
# the same personId/teamId pair as V2 for every paired event.
NON_ROSTER_ACTOR_FOULS = ("Technical", "Double Technical")
# V2 never records a fouled player for these subtypes (paired 2024-25 season),
# so their missing fouled player is not a V3 attribution gap.
FOULS_WITHOUT_FOULED_PLAYER = {
    "",
    "Technical",
    "Non-Unsportsmanlike Technical",
    "Hanging Technical",
    "Defense 3 Second",
    "Delay Technical",
    "Excess Timeout Technical",
    "Too Many Players Technical",
    "Flopping",
    "Bench",
}
# V2 records the second named player of a double foul as PLAYER2, always on
# the opposing team. A coach's double technical names no second person in V3.
DOUBLE_FOULS = {
    "Double Personal": re.compile(
        r"Foul : Double Personal - (.+?) \(\d+ PF\), (.+?) \(\d+ PF\)(?: \([^()]*\))?"
    ),
    "Double Technical": re.compile(r"Double Technical - (.+?), (.+?)(?: \([^()]*\))?"),
}
FREE_THROWS = {(1, 1): 10, (1, 2): 11, (2, 2): 12, (1, 3): 13, (2, 3): 14, (3, 3): 15}
# Recorded V2 codes and native V3 labels are pinned independently in
# tests/parity/free-throw-vocabulary.json; original FT behavior is retained.
FLAGRANT_FREE_THROWS = {
    (1, 1): 20, (1, 2): 18, (2, 2): 19,
    (1, 3): 27, (2, 3): 28, (3, 3): 29,
}
CLEAR_PATH_FREE_THROWS = {(1, 2): 25, (2, 2): 26}
TECHNICAL_FREE_THROWS = {(1, 2): 21, (2, 2): 22}
# Every supported subtype has recorded evidence in shot-vocabulary.json, and
# the paired 2024-25 exports record exactly these codes. Other codes once used
# for the same labels are historical (unresolved_aliases). No generic fallback.
SHOT_CODES = {
    "Alley Oop Dunk Shot": 52,
    "Alley Oop Layup shot": 43,
    "Cutting Dunk Shot": 108,
    "Cutting Finger Roll Layup Shot": 99,
    "Cutting Layup Shot": 98,
    "Driving Dunk Shot": 9,
    "Driving Bank Hook Shot": 93,
    "Driving Reverse Dunk Shot": 109,
    "Driving Finger Roll Layup Shot": 75,
    "Driving Floating Bank Jump Shot": 102,
    "Driving Floating Jump Shot": 101,
    "Driving Hook Shot": 57,
    "Driving Layup Shot": 6,
    "Driving Reverse Layup Shot": 73,
    "Dunk Shot": 7,
    "Fadeaway Jump Shot": 63,
    "Fadeaway Bank shot": 83,
    "Finger Roll Layup Shot": 71,
    "Floating Jump shot": 78,
    "Hook Shot": 3,
    "Hook Bank Shot": 67,
    "Jump Bank Shot": 66,
    "Jump Shot": 1,
    "Layup Shot": 5,
    "Pullup Jump shot": 79,
    "Putback Layup Shot": 72,
    "Putback Dunk Shot": 87,
    "Reverse Layup Shot": 44,
    "Reverse Dunk Shot": 51,
    "Running Alley Oop Layup Shot": 100,
    "Running Alley Oop Dunk Shot": 106,
    "Running Dunk Shot": 50,
    "Running Finger Roll Layup Shot": 76,
    "Running Jump Shot": 2,
    "Running Layup Shot": 41,
    "Running Reverse Layup Shot": 74,
    "Running Reverse Dunk Shot": 110,
    "Running Pull-Up Jump Shot": 103,
    "Step Back Jump shot": 80,
    "Step Back Bank Jump Shot": 104,
    "Tip Dunk Shot": 107,
    "Tip Layup Shot": 97,
    "Turnaround Bank Hook Shot": 96,
    "Turnaround Bank shot": 85,
    "Turnaround Fadeaway Bank Jump Shot": 105,
    "Turnaround Fadeaway shot": 86,
    "Turnaround Hook Shot": 58,
    "Turnaround Jump Shot": 47,
}
CLOCK = re.compile(r"PT(\d+)M(\d+(?:\.\d+)?)S")


def clock_text(value):
    match = CLOCK.fullmatch(value) if isinstance(value, str) else None
    if not match or Decimal(match[2]) >= 60:
        raise V3DecodeError("Invalid V3 clock: {!r}".format(value))
    seconds = Decimal(match[2])
    text = (
        format(seconds, "f").rstrip("0").rstrip(".")
        if "." in match[2]
        else str(int(seconds))
    )
    integer, dot, fraction = text.partition(".")
    return "{}:{}{}".format(
        int(match[1]), integer.zfill(2), dot + fraction if dot else ""
    )


class DecodedV3:
    def __init__(self, source_bytes, context):
        context = deepcopy(context)
        context.validate(source_bytes)
        self.source_bytes = bytes(source_bytes)
        self.context = context
        try:
            self.payload = json.loads(source_bytes)
        except ValueError as error:
            raise V3DecodeError("Source bytes are not valid JSON") from error
        game = self.payload.get("game", {}) if isinstance(self.payload, dict) else {}
        if game.get("gameId") != context.game_id or not isinstance(
            game.get("actions"), list
        ):
            raise V3DecodeError("V3 envelope does not match game/context")
        self.raw_rows = deepcopy(game["actions"])
        self.groups = {}
        self.projected = []
        self.unknown_attribution = []
        self.participant_resolutions = []
        self.non_roster_actors = []
        self.team_heaves = {}
        self._names = defaultdict(set)
        for player, facts in context.roster.items():
            for name in facts["names"]:
                self._names[(facts["team_id"], name.strip().casefold())].add(player)
        candidates = defaultdict(list)
        action_ids = set()
        for index, row in enumerate(self.raw_rows):
            if not isinstance(row, dict):
                raise V3DecodeError("Source row {} is not an object".format(index))
            for key in ("actionNumber", "actionId", "period", "personId", "teamId"):
                if type(row.get(key)) is not int or row[key] < 0:
                    raise V3DecodeError("Source row {}: invalid {}".format(index, key))
            if row["period"] <= 0 or row["actionId"] in action_ids:
                raise V3DecodeError(
                    "Invalid period or duplicate actionId at row {}".format(index)
                )
            action_ids.add(row["actionId"])
            clock_text(row.get("clock"))
            if any(
                not isinstance(row.get(key), str)
                for key in ("actionType", "subType", "description")
            ):
                raise V3DecodeError("Invalid event text at row {}".format(index))
            candidates[row["actionNumber"]].append((index, row))
        groups = []
        for number, rows in candidates.items():
            primary = [(i, row) for i, row in rows if row["actionType"]]
            if (
                len(primary) != 1
                or len({(row["period"], clock_text(row["clock"])) for _, row in rows})
                != 1
            ):
                raise V3DecodeError("Ambiguous action group {}".format(number))
            groups.append((primary[0][0], primary[0][1], rows))
        active_period, active_players = None, None
        for index, row, group in sorted(groups, key=lambda group: group[0]):
            try:
                if row["period"] != active_period:
                    active_period = row["period"]
                    active_players = (
                        {
                            p
                            for players in context.period_starters.get(
                                active_period, {}
                            ).values()
                            for p in players
                        }
                        if active_period in context.period_starters
                        else None
                    )
                projected = self._decode(row, group, active_players)
                if projected["EVENTMSGTYPE"] == 8 and active_players is not None:
                    outgoing, incoming = (
                        projected["PLAYER1_ID"],
                        projected["PLAYER2_ID"],
                    )
                    if outgoing not in active_players or incoming in active_players:
                        raise V3DecodeError(
                            "Substitution contradicts recorded starter/substitution stream"
                        )
                    active_players.remove(outgoing)
                    active_players.add(incoming)
            except V3DecodeError as error:
                raise V3DecodeError(
                    "Game {}, source rows {}: {}".format(
                        context.game_id, [i for i, _ in group], error
                    )
                ) from error
            self.groups[row["actionNumber"]] = dict(
                primary_index=index,
                source_indices=tuple(i for i, _ in group),
                primary=deepcopy(row),
            )
            self.projected.append(projected)
        if not self.projected:
            raise V3DecodeError("Empty play-by-play")

    def _resolve(self, name, team=None, *, active_players=None, event_num=None):
        candidates = set()
        for candidate_team in self.context.team_ids if team is None else (team,):
            candidates.update(
                self._names.get((candidate_team, name.strip().casefold()), ())
            )
        if len(candidates) > 1 and active_players is not None:
            eligible = candidates & active_players
            if len(eligible) == 1:
                selected = next(iter(eligible))
                self.participant_resolutions.append(
                    dict(
                        event_num=event_num,
                        role="tip_recipient",
                        name=name,
                        candidates=sorted(candidates),
                        player_id=selected,
                        on_court=sorted(active_players),
                        basis="recorded_starters_and_substitutions",
                    )
                )
                return selected
        if len(candidates) != 1:
            raise V3DecodeError(
                "Participant {!r} is unresolved or ambiguous".format(name)
            )
        return next(iter(candidates))

    def _decode(self, row, group, active_players):
        kind, subtype = row["actionType"], row["subType"]
        team, player = row["teamId"], row["personId"]
        if kind == "Heave":
            team = self._team_heave_team(row)
        if player in self.context.team_ids:
            if team not in (0, player):
                raise V3DecodeError("Team-valued personId contradicts teamId")
            team, player = player, 0
        if team and team not in self.context.team_ids:
            raise V3DecodeError("Unknown event team")
        non_roster = (
            player
            and player not in self.context.roster
            and (
                kind == "Ejection"
                or kind == "Foul"
                and subtype in NON_ROSTER_ACTOR_FOULS
            )
        )
        if non_roster:
            # Pass the recorded pair through, as V2 records it. Without a team,
            # the original Stats event treats the person ID as its team, as it
            # does for V2 coaches.
            self.non_roster_actors.append(
                dict(
                    code="non_roster_actor",
                    event_num=row["actionNumber"],
                    person_id=player,
                    team_id=team or None,
                    basis="recorded_personId_and_teamId_as_in_v2",
                )
            )
        elif player and kind != "Instant Replay":
            if player not in self.context.roster:
                raise V3DecodeError("Actor missing from recorded roster")
            recorded_team = self.context.roster[player]["team_id"]
            if team and team != recorded_team:
                raise V3DecodeError("Actor and team disagree")
            team = recorded_team
        if (
            kind in ("Made Shot", "Missed Shot", "Free Throw", "Substitution")
            and not player
        ):
            raise V3DecodeError("Event requires a player actor")
        if (
            kind
            in (
                "Made Shot",
                "Missed Shot",
                "Free Throw",
                "Rebound",
                "Turnover",
                "Foul",
                "Substitution",
            )
            and not team
            and not non_roster
        ):
            raise V3DecodeError("Event requires a known team")
        event = dict(
            GAME_ID=self.context.game_id,
            EVENTNUM=row["actionNumber"],
            PERIOD=row["period"],
            PCTIMESTRING=clock_text(row["clock"]),
            PLAYER1_ID=player,
            PLAYER1_TEAM_ID=team or None,
            PLAYER2_ID=None,
            PLAYER3_ID=None,
            PLAYER3_TEAM_ID=None,
            NEUTRALDESCRIPTION=row["description"],
            EVENTMSGACTIONTYPE=0,
        )
        roles = {}
        for _, secondary in group:
            if secondary is row:
                continue
            role = (
                "stealer"
                if re.fullmatch(r".+ STEAL \(\d+ STL\)", secondary["description"])
                else (
                    "blocker"
                    if re.fullmatch(r".+ BLOCK \(\d+ BLK\)", secondary["description"])
                    else None
                )
            )
            if (
                role is None
                or role in roles
                or (role, kind)
                not in (("stealer", "Turnover"), ("blocker", "Missed Shot"), ("blocker", "Heave"))
            ):
                raise V3DecodeError("Unsupported or conflicting secondary row")
            identity = secondary["personId"]
            if kind == "Heave" and role == "blocker" and identity == 0:
                opposing = next(t for t in self.context.team_ids if t != team)
                name = re.fullmatch(r"(.+) BLOCK \(\d+ BLK\)", secondary["description"])[1]
                identity = self._resolve(name, opposing)
                if secondary.get("location") not in ("", {"h": "v", "v": "h"}[row["location"]]):
                    raise V3DecodeError("Team-heave blocker location contradicts opposing team")
                self.team_heaves[row["actionNumber"]]["blocker"] = dict(
                    source_index=next(i for i, r in group if r is secondary),
                    action_number=row["actionNumber"], role="blocker",
                    name=name, player_id=identity, team_id=opposing,
                    basis="team_heave_opposing_roster_name",
                )
            if (
                identity not in self.context.roster
                or self.context.roster[identity]["team_id"] == team
            ):
                raise V3DecodeError(
                    "Secondary participant must belong to the opposing roster"
                )
            if secondary["teamId"] not in (0, self.context.roster[identity]["team_id"]):
                raise V3DecodeError("Secondary participant and team disagree")
            roles[role] = identity
        if kind in ("Made Shot", "Missed Shot"):
            made = kind == "Made Shot"
            if (
                type(row.get("shotValue")) is not int
                or row["shotValue"] not in (2, 3)
                or row.get("shotResult") != ("Made" if made else "Missed")
                or type(row.get("isFieldGoal")) is not int
                or row["isFieldGoal"] != 1
            ):
                raise V3DecodeError("Inconsistent field goal facts")
            if (
                row["description"].startswith("MISS ") == made
                or row["shotValue"] == 2
                and "3PT" in row["description"]
            ):
                raise V3DecodeError("Description contradicts field goal facts")
            if subtype not in SHOT_CODES:
                raise V3DecodeError("Unsupported shot subtype {!r}".format(subtype))
            event.update(
                EVENTMSGTYPE=1 if made else 2, EVENTMSGACTIONTYPE=SHOT_CODES[subtype]
            )
            # Shared shot value reads the description; retain explicit V3 value in
            # the derived constructor description while leaving raw text intact.
            if row["shotValue"] == 3 and "3PT" not in event["NEUTRALDESCRIPTION"]:
                event["NEUTRALDESCRIPTION"] += " 3PT "
            assist = re.search(r"\(([^()]+?) \d+ AST\)", row["description"])
            if assist:
                if not made:
                    raise V3DecodeError("A missed shot cannot have an assist")
                event["PLAYER2_ID"] = self._resolve(assist[1], team)
            event["PLAYER3_ID"] = roles.get("blocker")
        elif kind == "Heave":
            # Missed-field-goal category for the original rebound/order methods;
            # a dedicated extension class supplies semantics, with no V2 subtype.
            event.update(EVENTMSGTYPE=2, EVENTMSGACTIONTYPE=None)
            event["PLAYER3_ID"] = roles.get("blocker")
        elif kind == "Free Throw":
            match = re.fullmatch(
                r"Free Throw(?: (Technical|Clear Path|Flagrant))? ([1-3]) of ([1-3])",
                subtype,
            )
            if subtype == "Free Throw Technical":
                code = 16
            elif match:
                category, attempt, total = match[1], int(match[2]), int(match[3])
                if attempt > total or category == "Clear Path" and total != 2:
                    raise V3DecodeError("Invalid free throw numbering")
                if category == "Technical":
                    if (attempt, total) not in TECHNICAL_FREE_THROWS:
                        raise V3DecodeError("Unsupported technical attempt pattern")
                    code = TECHNICAL_FREE_THROWS[attempt, total]
                elif category == "Clear Path":
                    code = CLEAR_PATH_FREE_THROWS[attempt, total]
                elif (
                    category == "Flagrant" and (attempt, total) in FLAGRANT_FREE_THROWS
                ):
                    code = FLAGRANT_FREE_THROWS[attempt, total]
                elif category is None:
                    code = FREE_THROWS[attempt, total]
                else:
                    raise V3DecodeError("Unsupported flagrant attempt pattern")
            else:
                raise V3DecodeError("Unsupported free throw subtype")
            event.update(EVENTMSGTYPE=3, EVENTMSGACTIONTYPE=code)
            # Outcome is described by MISS; category/numbering must be explicit.
            if subtype not in row["description"]:
                raise V3DecodeError("Free throw description disagrees with subtype")
        elif kind in ("Foul", "Turnover", "Violation"):
            table = {"Foul": FOULS, "Turnover": TURNOVERS, "Violation": VIOLATIONS}[
                kind
            ]
            if subtype not in table:
                raise V3DecodeError("Unsupported {} subtype {!r}".format(kind, subtype))
            event.update(
                EVENTMSGTYPE={"Foul": 6, "Turnover": 5, "Violation": 7}[kind],
                EVENTMSGACTIONTYPE=table[subtype],
            )
            if kind == "Turnover":
                event["PLAYER2_ID"] = roles.get("stealer")
            elif kind == "Foul" and subtype in DOUBLE_FOULS and not non_roster:
                match = DOUBLE_FOULS[subtype].fullmatch(row["description"].strip())
                if not match or self._resolve(match[1], team) != player:
                    raise V3DecodeError("Double foul requires both recorded participants")
                opponent = next(t for t in self.context.team_ids if t != team)
                try:
                    event["PLAYER2_ID"] = self._resolve(match[2], opponent)
                except V3DecodeError:
                    # The other party of a double technical can be a coach, for
                    # whom V3 records no ID. The original's decisions and
                    # statistics ignore it; a double personal must resolve.
                    if subtype != "Double Technical":
                        raise
                    self.unknown_attribution.append(
                        dict(
                            event_num=row["actionNumber"],
                            role="double_foul_opponent",
                            name=match[2],
                        )
                    )
            elif kind == "Foul" and subtype in DOUBLE_FOULS:
                self.unknown_attribution.append(
                    dict(event_num=row["actionNumber"], role="double_foul_opponent")
                )
            elif kind == "Foul" and subtype not in FOULS_WITHOUT_FOULED_PLAYER:
                self.unknown_attribution.append(
                    dict(event_num=row["actionNumber"], role="foul_drawn")
                )
        elif kind == "Rebound":
            if subtype not in REBOUNDS:
                raise V3DecodeError("Unsupported rebound subtype")
            # Code 1 is V2's placeholder rebound; the original's is_placeholder
            # reads it, so it is a decision input rather than a label.
            event.update(EVENTMSGTYPE=4, EVENTMSGACTIONTYPE=REBOUNDS[subtype])
        elif kind == "Substitution":
            match = re.fullmatch(r"SUB: (.+) FOR (.+)", row["description"])
            if subtype or not match or self._resolve(match[2], team) != player:
                raise V3DecodeError(
                    "Substitution description contradicts outgoing player"
                )
            event.update(EVENTMSGTYPE=8, PLAYER2_ID=self._resolve(match[1], team))
        elif kind == "Jump Ball":
            # Coach-challenge descriptions carry a "(CC) " marker, others never do.
            marker = r"\(CC\) " if subtype == "Coach Challenge" else ""
            match = re.fullmatch(
                r"Jump Ball " + marker + r"(.+) vs\. (.+): Tip to (.+)",
                row["description"],
            )
            if (
                subtype not in JUMP_BALLS
                or not match
                or self._resolve(match[1], team) != player
            ):
                raise V3DecodeError(
                    "Jump ball requires explicit resolvable participant roles"
                )
            opponent = next(t for t in self.context.team_ids if t != team)
            recipient = self._resolve(
                match[3], active_players=active_players, event_num=row["actionNumber"]
            )
            event.update(
                EVENTMSGTYPE=10,
                EVENTMSGACTIONTYPE=JUMP_BALLS[subtype],
                PLAYER2_ID=self._resolve(match[2], opponent),
                PLAYER3_ID=recipient,
                PLAYER3_TEAM_ID=self.context.roster[recipient]["team_id"],
            )
        elif kind == "period" and subtype in ("start", "end"):
            event["EVENTMSGTYPE"] = 12 if subtype == "start" else 13
        elif kind == "Timeout" and subtype in TIMEOUTS:
            event.update(EVENTMSGTYPE=9, EVENTMSGACTIONTYPE=TIMEOUTS[subtype])
        elif kind == "Instant Replay" and subtype in REPLAYS:
            event.update(EVENTMSGTYPE=18, EVENTMSGACTIONTYPE=REPLAYS[subtype])
        elif kind == "Ejection" and subtype in EJECTIONS:
            event.update(EVENTMSGTYPE=11, EVENTMSGACTIONTYPE=EJECTIONS[subtype])
        else:
            raise V3DecodeError(
                "Unsupported event type/subtype {!r}/{!r}".format(kind, subtype)
            )
        return event

    def _team_heave_team(self, row):
        from .team_heave import TEAM_HEAVE_VERSION

        # Trust the feed's explicit classification; do not reclassify player shots
        # using distance/time thresholds or infer who attempted the shot.
        if (
            int(self.context.game_id[3:5]) < 25
            or row["subType"] != "Team Field Goal Attempt"
            or row["personId"] != 0
            or any(type(row.get(k)) is not int or row[k] != 0
                   for k in ("isFieldGoal", "shotValue", "shotDistance", "xLegacy", "yLegacy"))
            or row.get("shotResult") != ""
            or any(row.get(k) for k in ("playerName", "playerNameI"))
        ):
            raise V3DecodeError("Unsupported or conflicting team-heave facts")
        location = row.get("location")
        witnesses = {}
        for index, source in enumerate(self.raw_rows):
            side, team = source.get("location"), source["teamId"]
            if side in ("h", "v") and team in self.context.team_ids:
                witnesses.setdefault(side, {}).setdefault(team, index)
        if (
            location not in ("h", "v")
            or set(witnesses) != {"h", "v"}
            or any(len(teams) != 1 for teams in witnesses.values())
            or set(witnesses["h"]) == set(witnesses["v"])
        ):
            raise V3DecodeError("Team heave requires unambiguous recorded home/away team evidence")
        team, index = next(iter(witnesses[location].items()))
        if row["teamId"] not in (0, team):
            raise V3DecodeError("Team-heave location contradicts teamId")
        self.team_heaves[row["actionNumber"]] = dict(
            code=TEAM_HEAVE_VERSION,
            event_num=row["actionNumber"],
            team_id=team,
            attribution="team",
            location=location,
            team_witness_source_index=index,
            basis="explicit_source_teamId_and_location",
        )
        return team
