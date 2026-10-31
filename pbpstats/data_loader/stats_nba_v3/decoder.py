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


# The original's own live play-by-play source (pbpstats.data_loader.live).
LIVE_PLAY_BY_PLAY_URL = (
    "https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/"
    "{league}/liveData/playbyplay/playbyplay_{game_id}.json"
)


LIVE_JUMP_BALL_FIELDS = (
    "period",
    "personId",
    "teamId",
    "jumpBallWonPersonId",
    "jumpBallLostPersonId",
)


# A jump ball's facts as a reviewed V2 export row records them (see overrides),
# with the export's own field names.
V2_JUMP_BALL_FIELDS = (
    "EVENTNUM",
    "EVENTMSGTYPE",
    "EVENTMSGACTIONTYPE",
    "PERIOD",
    "PCTIMESTRING",
    "HOMEDESCRIPTION",
    "NEUTRALDESCRIPTION",
    "VISITORDESCRIPTION",
    "PERSON1TYPE",
    "PLAYER1_ID",
    "PERSON2TYPE",
    "PLAYER2_ID",
    "PERSON3TYPE",
    "PLAYER3_ID",
)
# V2 person types: 2/3 a home/visitor team, 4/5 a home/visitor player.
V2_TEAM_TYPES, V2_PLAYER_TYPES = (2, 3), (4, 5)


# NBA 2019-20 records most team technicals (a delay technical, or a technical)
# with neither a team nor a person in V3 and V2 alike: 22 of 33 delay
# technicals and 3 of 4 technicals. 2020-21 records 2 of 18 delay technicals
# so; 2018-19 and 2021-22 to 2025-26 always record the team.
TEAMLESS_TECHNICAL_VERSION = "nba_teamless_team_technical_v1"
TEAMLESS_TECHNICALS = ("Technical", "Delay Technical")
# NBA 2026-27 V3 records the free throw for a defensive three seconds, a
# hanging or delay technical or a flopping foul as "Free Throw 1 of 1", though
# still "Free Throw Technical" for a technical. From 2017-18 to 2025-26, 7,165
# of the 7,172 lone free throws for the team's only technical-type foul at its
# clock record "Free Throw Technical", V2's 16; six in 2017-18 record 1 of 1,
# and one a numbered technical. All 103 for a flopping foul, recorded from
# 2023-24, do too. Version 1 decoded only a defensive three seconds' free
# throw; version 2 missed fouls recorded with the team as the person, and
# flopping fouls.
TECHNICAL_FREE_THROW_VERSION = "nba_technical_free_throw_v3"
# NBA 2026-27 V3 records a transition take foul as a "Personal Take" foul, with
# its one free throw. From 2022-23 to 2025-26, 575 transition take fouls with one
# free throw and no other foul by the team at its clock record "Transition
# Take", V2's 31. A "Personal Take" with that free throw is otherwise recorded 5
# times from 2017-18: 4 with the team in the penalty (".PN"), and 2024-25 game
# 0022400625's, which video review found to be a transition take foul.
TRANSITION_TAKE_FOUL_VERSION = "nba_transition_take_foul_v1"
TEAM_FOUL_COUNT = re.compile(r"\(P\d+\.T\d+\)")
# NBA V3 records an excess timeout's turnover with neither a team nor a person
# in four games from 2020-21 to 2022-23, and its technical so in one of them
# (0022000285); from 2017-18 to 2025-26 the 9 other excess timeout turnovers
# and the 17 other excess timeout technicals record their team. The team
# charged is the one that did not shoot the technical free throw.
TEAMLESS_EXCESS_TIMEOUT_VERSION = "nba_teamless_excess_timeout_v1"
EXCESS_TIMEOUTS = ("Excess Timeout Technical", "Excess Timeout Turnover")
# NBA 2026-27 V3 records the three free throws of two flagrant 1 fouls with
# neither category nor numbering, in subtype or text (0022600091, 0022600099),
# each after a replay that overturned the call; from 2017-18 to 2025-26 all
# 2,826 flagrant free throws record both. Such a free throw is its trip's
# attempt in recorded order.
BLANK_FLAGRANT_FREE_THROW_VERSION = "nba_blank_flagrant_free_throw_v1"
# When the shooting team's lane violation or offensive goaltending voids a
# shooting foul's second free throw, NBA V3 records the made first one as "Free
# Throw 1 of 2" 39 of 43 times from 2017-18 to 2025-26, and never 1 of 3. The
# other four record "Free Throw 1 of 1", which the original reads as the trip's
# last free throw, so the possession ends before the turnover.
VOIDED_SECOND_FREE_THROW_VERSION = "nba_voided_second_free_throw_v1"
VOIDING_TURNOVERS = ("Lane Violation", "Offensive Goaltending")


def live_play_by_play_url(game_id):
    league = "WNBA" if game_id.startswith("10") else "NBA"
    return LIVE_PLAY_BY_PLAY_URL.format(league=league, game_id=game_id)


class V3JumpBallEvidenceRequired(V3DecodeError):
    """A jump ball V3 leaves undecided; ``url`` is the live play-by-play that records it.

    The adapter never makes the request. A caller records the response and
    passes it back as V3JumpBallEvidence.
    """

    def __init__(self, message, *, url):
        super().__init__(message)
        self.url = url


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
            r"(00|10)\d{8}", self.game_id
        ):
            raise V3DecodeError(
                "Compatibility adapter supports NBA and WNBA game IDs only"
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


# The labels the decoder accepts for each kind of event. The native event
# classes decide from them; tools/parity/v2_codes.py pins the V2 code each one
# is checked against. A blank subtype is a label too, e.g. the original's
# no-turnover.
FOULS = (
    "",
    "Personal",
    "Shooting",
    "Loose Ball",
    "Offensive",
    "Inbound",
    "Away From Play",
    "Punching",
    "Clear Path",
    "Double Personal",
    "Technical",
    "Non-Unsportsmanlike Technical",
    "Hanging Technical",
    "Flagrant Type 1",
    "Flagrant Type 2",
    "Double Technical",
    "Defense 3 Second",
    "Delay Technical",
    "Excess Timeout Technical",
    "Offensive Charge",
    "Personal Block",
    "Personal Take",
    "Shooting Block",
    "Too Many Players Technical",
    "Transition Take",
    "Flopping",
    "Bench",
)
TURNOVERS = (
    "",
    "Bad Pass",
    "Lost Ball",
    "Traveling",
    "Double Dribble",
    "Discontinue Dribble",
    "3 Second Violation",
    "5 Second Violation",
    "8 Second Violation",
    "Shot Clock Turnover",
    "Inbound Turnover",
    "Backcourt Turnover",
    "Offensive Goaltending",
    "Lane Violation",
    "Jump Ball Violation",
    "Kicked Ball Violation",
    "Illegal Assist Turnover",
    "Palming Turnover",
    "10 Second Violaton",
    "Punched Ball Turnover",
    "Swinging Elbows Turnover",
    "Basket from Below Turnover",
    "Illegal Screen Turnover",
    "Offensive Foul Turnover",
    "Step Out of Bounds Turnover",
    "Out of Bounds Lost Ball Turnover",
    "Excess Timeout Turnover",
    "Too Many Players Turnover",
    "Out of Bounds - Bad Pass Turnover",
)
# Turnovers V3 records as a team's, with the team as the person: every team
# turnover from 2021-22 to 2025-26 is one of these (Shot Clock 8,301, 5 Second
# 276, 8 Second 234, Too Many Players 3), as is the excess timeout turnover
# 0022200323 records without a team.
TEAM_TURNOVERS = {
    "5 Second Violation",
    "8 Second Violation",
    "Shot Clock Turnover",
    "Excess Timeout Turnover",
    "Too Many Players Turnover",
}
VIOLATIONS = (
    "Delay Of Game",
    "Defensive Goaltending",
    "Lane",
    "Jump Ball",
    "Kicked Ball",
    "Double Lane",
)
REBOUNDS = ("Unknown", "Normal Rebound")
# V3 records a short timeout in 2015-16, 2016-17 and again in 2026-27.
TIMEOUTS = ("Regular", "Short", "Coach Challenge")
JUMP_BALLS = ("", "Coach Challenge")
REPLAYS = (
    "Support Ruling",
    "Overturn Ruling",
    "Altercation Ruling",
    "Ruling Stands",
    "Coach Challenge Support Ruling",
    "Coach Challenge Overturn Ruling",
    "Coach Challenge Ruling Stands",
    "Replay Center",
)
# V3 labels a flagrant 2 ejection "Other" from 2017-18 to 2025-26, but "First
# Flagrant Type 2" in 2015-16, 2016-17 and again in 2026-27. A second-technical
# ejection is likewise "Second Technical" in those seasons. 2026-27 V3 also
# labels an ejection for a second flagrant 1 "Second Flagrant Type 1"
# (0022600105), which no V2 export records; the original never reads an
# ejection's kind.
EJECTIONS = ("Other", "First Flagrant Type 2", "Second Technical", "Second Flagrant Type 1")
# The fouls the original classes as technical or double technical, its V2 codes
# 11, 12, 13, 16, 18, 19, 25 and 30 (no V3 label records 19). Their actors can
# be outside the player roster: coaches (no team in either feed) and inactive
# players (with their team). V3 records the same personId/teamId pair as V2 for
# every paired event. The original never checks a roster, and its starter
# inference skips the actor of each of these fouls, "because a player could
# get a technical foul when they aren't in the game".
TECHNICAL_FOULS = (
    "Technical",
    "Non-Unsportsmanlike Technical",
    "Hanging Technical",
    "Double Technical",
    "Delay Technical",
    "Excess Timeout Technical",
    "Too Many Players Technical",
)
# Fouls that award one technical free throw: a defensive three seconds, a
# flopping foul, and those the original classes as technical, but a double
# technical, which awards none.
TECHNICAL_FREE_THROW_FOULS = ("Defense 3 Second", "Flopping") + tuple(
    label for label in TECHNICAL_FOULS if label != "Double Technical"
)
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
# A double foul's second named player, always on the opposing team, is its
# player 3, as the original reads the second player V2 records. A coach's
# double technical names no second person in V3.
DOUBLE_FOULS = {
    "Double Personal": re.compile(
        r"Foul : Double Personal - (.+?) \(\d+ PF\), (.+?) \(\d+ PF\)(?: \([^()]*\))?"
    ),
    "Double Technical": re.compile(r"Double Technical - (.+?), (.+?)(?: \([^()]*\))?"),
}
# Free throw numbering, (attempt, total): any for a regular or flagrant free
# throw, only these for a clear path or technical one.
FREE_THROWS = {(1, 1), (1, 2), (2, 2), (1, 3), (2, 3), (3, 3)}
CLEAR_PATH_FREE_THROWS = {(1, 2), (2, 2)}
TECHNICAL_FREE_THROWS = {(1, 2), (2, 2)}
# Recorded only in the paired WNBA 2025 exports (tests/parity/paired-season-wnba-2025.json),
# so they decode for WNBA games alone; NBA games still reject them.
WNBA_TIMEOUTS = ("Official", "Reset")
WNBA_CLEAR_PATH_FREE_THROWS = {(1, 1)}
# Every supported subtype has recorded evidence in shot-vocabulary.json. No
# generic fallback.
SHOTS = (
    "Alley Oop Dunk Shot",
    "Alley Oop Layup shot",
    "Cutting Dunk Shot",
    "Cutting Finger Roll Layup Shot",
    "Cutting Layup Shot",
    "Driving Dunk Shot",
    "Driving Bank Hook Shot",
    "Driving Reverse Dunk Shot",
    "Driving Finger Roll Layup Shot",
    "Driving Floating Bank Jump Shot",
    "Driving Floating Jump Shot",
    "Driving Hook Shot",
    "Driving Layup Shot",
    "Driving Reverse Layup Shot",
    "Dunk Shot",
    "Fadeaway Jump Shot",
    "Fadeaway Bank shot",
    "Finger Roll Layup Shot",
    "Floating Jump shot",
    "Hook Shot",
    "Hook Bank Shot",
    "Jump Bank Shot",
    "Jump Shot",
    "Layup Shot",
    "Pullup Jump shot",
    "Putback Layup Shot",
    "Putback Dunk Shot",
    "Reverse Layup Shot",
    "Reverse Dunk Shot",
    "Running Alley Oop Layup Shot",
    "Running Alley Oop Dunk Shot",
    "Running Dunk Shot",
    "Running Finger Roll Layup Shot",
    "Running Jump Shot",
    "Running Layup Shot",
    "Running Reverse Layup Shot",
    "Running Reverse Dunk Shot",
    "Running Pull-Up Jump Shot",
    "Step Back Jump shot",
    "Step Back Bank Jump Shot",
    "Tip Dunk Shot",
    "Tip Layup Shot",
    "Turnaround Bank Hook Shot",
    "Turnaround Bank shot",
    "Turnaround Fadeaway Bank Jump Shot",
    "Turnaround Fadeaway shot",
    "Turnaround Hook Shot",
    "Turnaround Jump Shot",
)
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


def v3_clock_seconds(value):
    """Seconds left in the period on a V3 clock that clock_text accepts."""
    match = CLOCK.fullmatch(value)
    return int(match[1]) * 60 + Decimal(match[2])


class DecodedV3:
    def __init__(
        self, source_bytes, context, jump_balls=None, locations=None, live_numbers=None,
        teams=None, foul_opponents=None, removed=(), block_removals=(),
        v2_jump_balls=None, free_throw_subtypes=None, substitution_outgoing=None,
    ):
        context = deepcopy(context)
        context.validate(source_bytes)
        self.source_bytes = bytes(source_bytes)
        self.context = context
        self.live_jump_balls, self.live_input = (
            jump_balls.decode(self.source_bytes, context.game_id)
            if jump_balls is not None
            else (None, None)
        )
        self.recorded_jump_balls = []
        # Reviewed facts an event cannot be decoded without (see overrides):
        # a team heave's side, a renumbered jump ball's live action, the team of
        # an event recorded with neither team nor person, the other party of
        # a double foul whose text names nobody, a missed shot's recorded
        # block that did not happen, the V2 export row of a jump ball V3
        # leaves undecided when no live play-by-play records the game, the
        # subtype of a free throw V3 records with none, and the player a
        # substitution took off when V3 names one already off. The recorded rows stay
        # unchanged; each fact must be used by its event.
        self.reviewed_locations = dict(locations or {})
        self.reviewed_live_numbers = dict(live_numbers or {})
        self.reviewed_teams = dict(teams or {})
        self.reviewed_foul_opponents = dict(foul_opponents or {})
        self.reviewed_block_removals = set(block_removals)
        self.reviewed_v2_jump_balls = dict(v2_jump_balls or {})
        self.reviewed_free_throw_subtypes = dict(free_throw_subtypes or {})
        self.reviewed_substitution_outgoing = dict(substitution_outgoing or {})
        self._unused_reviewed = {
            "location": set(self.reviewed_locations),
            "live-number": set(self.reviewed_live_numbers),
            "team": set(self.reviewed_teams),
            "foul-opponent": set(self.reviewed_foul_opponents),
            "block-removal": set(self.reviewed_block_removals),
            "v2-jump-ball": set(self.reviewed_v2_jump_balls),
            "free-throw-subtype": set(self.reviewed_free_throw_subtypes),
            "substitution-outgoing": set(self.reviewed_substitution_outgoing),
        }
        self.team_technicals = []
        self.label_rules = []
        # Events a reviewed removal drops are not part of the recorded
        # starter/substitution stream.
        self.reviewed_removed = set(removed)
        wnba = context.game_id.startswith("10")
        self.timeouts = TIMEOUTS + WNBA_TIMEOUTS if wnba else TIMEOUTS
        self.clear_path_free_throws = (
            CLEAR_PATH_FREE_THROWS | WNBA_CLEAR_PATH_FREE_THROWS
            if wnba
            else CLEAR_PATH_FREE_THROWS
        )
        # WNBA 2025 V2 names a fouled player for its one blank-subtype foul.
        self.fouls_without_fouled_player = (
            FOULS_WITHOUT_FOULED_PLAYER - {""} if wnba else FOULS_WITHOUT_FOULED_PLAYER
        )
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
        self.reviewed_inputs = []
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
                if (
                    projected["action_type"] == "Substitution"
                    and active_players is not None
                    and row["actionNumber"] not in self.reviewed_removed
                ):
                    outgoing, incoming = projected["player1_id"], projected["player2_id"]
                    if outgoing not in active_players or incoming in active_players:
                        raise V3DecodeError(
                            "Substitution contradicts recorded starter/substitution stream"
                        )
                    active_players.remove(outgoing)
                    active_players.add(incoming)
            except V3DecodeError as error:
                message = "Game {}, source rows {}: {}".format(
                    context.game_id, [i for i, _ in group], error
                )
                if isinstance(error, V3JumpBallEvidenceRequired):
                    raise V3JumpBallEvidenceRequired(message, url=error.url) from error
                raise V3DecodeError(message) from error
            self.groups[row["actionNumber"]] = dict(
                primary_index=index,
                source_indices=tuple(i for i, _ in group),
                primary=deepcopy(row),
            )
            self.projected.append(projected)
        if not self.projected:
            raise V3DecodeError("Empty play-by-play")
        for kind, events in sorted(self._unused_reviewed.items()):
            if events:
                raise V3DecodeError(
                    "Event {} override does not fit the recorded event".format(kind)
                )

    def _candidates(self, name, team=None):
        return {
            player
            for candidate_team in (self.context.team_ids if team is None else (team,))
            for player in self._names.get((candidate_team, name.strip().casefold()), ())
        }

    def _resolve(self, name, team=None, *, active_players=None, event_num=None):
        candidates = self._candidates(name, team)
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
        if row["actionNumber"] in self.reviewed_teams:
            # Only an event V3 records with neither a team nor a person, given
            # the team as V3 records a team's own event: no person.
            reviewed = self.reviewed_teams[row["actionNumber"]]
            if kind == "Heave" or team or player or reviewed not in self.context.team_ids:
                raise V3DecodeError("Event team override does not fit the recorded event")
            self._unused_reviewed["team"].discard(row["actionNumber"])
            team = reviewed
            self.reviewed_inputs.append(
                dict(code="reviewed_event_team", event_num=row["actionNumber"], team_id=team)
            )
        if team and team not in self.context.team_ids:
            raise V3DecodeError("Unknown event team")
        if kind == "Foul" and subtype in TEAMLESS_TECHNICALS and not team and not player:
            team = self._teamless_technical_team(row)
        elif (
            kind in ("Foul", "Turnover") and subtype in EXCESS_TIMEOUTS
            and not team and not player
        ):
            team = self._teamless_excess_timeout_team(row)
        non_roster = (
            player
            and player not in self.context.roster
            and (
                kind == "Ejection"
                or kind == "Foul"
                and subtype in TECHNICAL_FOULS
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
            game_id=self.context.game_id,
            event_num=row["actionNumber"],
            period=row["period"],
            clock=clock_text(row["clock"]),
            description=row["description"],
            # The labels native event classes decide from, as a rule or a
            # reviewed correction leaves them.
            action_type=kind,
            sub_type=subtype,
            # The people, by the roles the original's events give them: player 2
            # is an assister, an incoming player or a jump ball's recipient;
            # player 3 a blocker, a stealer, a double foul's other party or the
            # other jumper. None is no one.
            team_id=team or None,
            player1_id=player,
            player2_id=None,
            player3_id=None,
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
            if (role, kind) == ("blocker", "Missed Shot") and (
                row["actionNumber"] in self.reviewed_block_removals
            ):
                # A reviewed block that did not happen: the miss is decoded as
                # V2 records it, with no blocker; the row stays in its group.
                self._unused_reviewed["block-removal"].discard(row["actionNumber"])
                self.reviewed_inputs.append(dict(
                    code="reviewed_block_removal", event_num=row["actionNumber"],
                    recorded_person_id=secondary["personId"],
                    description=secondary["description"],
                ))
                continue
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
            if subtype not in SHOTS:
                raise V3DecodeError("Unsupported shot subtype {!r}".format(subtype))
            # Shared shot value reads the description; retain explicit V3 value in
            # the derived constructor description while leaving raw text intact.
            if row["shotValue"] == 3 and "3PT" not in event["description"]:
                event["description"] += " 3PT "
            assist = re.search(r"\(([^()]+?) \d+ AST\)", row["description"])
            if assist:
                if not made:
                    raise V3DecodeError("A missed shot cannot have an assist")
                event["player2_id"] = self._resolve(assist[1], team)
            event["player3_id"] = roles.get("blocker")
        elif kind == "Heave":
            # A missed field goal, whose team-heave class supplies the rest.
            event["player3_id"] = roles.get("blocker")
        elif kind == "Free Throw":
            description = row["description"]
            if row["actionNumber"] in self.reviewed_free_throw_subtypes:
                # A free throw V3 records with neither category nor numbering,
                # in its subtype or its text: the reviewed subtype, which the
                # derived text then names as V3's would.
                reviewed = self.reviewed_free_throw_subtypes[row["actionNumber"]]
                if subtype or not re.fullmatch(
                    r"(?:MISS )?.+ Free Throw(?: \(\d+ PTS\))?", description
                ):
                    raise V3DecodeError(
                        "Event free-throw-subtype override does not fit the recorded event"
                    )
                self._unused_reviewed["free-throw-subtype"].discard(row["actionNumber"])
                subtype = reviewed
                description = description.replace(" Free Throw", " " + reviewed, 1)
                self.reviewed_inputs.append(dict(
                    code="reviewed_free_throw_subtype", event_num=row["actionNumber"],
                    subtype=reviewed,
                ))
            elif not subtype and self._blank_flagrant_free_throw(row, team):
                subtype = self.label_rules[-1]["decoded"]
                description = description.replace(" Free Throw", " " + subtype, 1)
            elif subtype == "Free Throw 1 of 1" and self._voided_second_free_throw(row, team):
                subtype = "Free Throw 1 of 2"
                description = description.replace("Free Throw 1 of 1", subtype)
            match = re.fullmatch(
                r"Free Throw(?: (Technical|Clear Path|Flagrant))? ([1-3]) of ([1-3])",
                subtype,
            )
            if subtype == "Free Throw 1 of 1" and self._technical_free_throw(row, team):
                # The original reads a technical free throw from its text.
                description = description.replace(subtype, "Free Throw Technical")
                subtype = "Free Throw Technical"
            elif subtype != "Free Throw Technical":
                if not match:
                    raise V3DecodeError("Unsupported free throw subtype")
                category, attempt, total = match[1], int(match[2]), int(match[3])
                if attempt > total or (
                    category == "Clear Path"
                    and (attempt, total) not in self.clear_path_free_throws
                ):
                    raise V3DecodeError("Invalid free throw numbering")
                if category == "Technical" and (attempt, total) not in TECHNICAL_FREE_THROWS:
                    raise V3DecodeError("Unsupported technical attempt pattern")
            event.update(description=description, sub_type=subtype)
            # Outcome is described by MISS; category/numbering must be explicit.
            if subtype not in description:
                raise V3DecodeError("Free throw description disagrees with subtype")
        elif kind in ("Foul", "Turnover", "Violation"):
            table = {"Foul": FOULS, "Turnover": TURNOVERS, "Violation": VIOLATIONS}[
                kind
            ]
            if subtype not in table:
                raise V3DecodeError("Unsupported {} subtype {!r}".format(kind, subtype))
            if kind == "Foul" and subtype == "Personal Take" and self._transition_take_foul(
                row, team
            ):
                event["sub_type"] = "Transition Take"
            if kind == "Turnover":
                event["player3_id"] = roles.get("stealer")
            elif kind == "Foul" and subtype in DOUBLE_FOULS and not non_roster:
                match = DOUBLE_FOULS[subtype].fullmatch(row["description"].strip())
                opponent = next(t for t in self.context.team_ids if t != team)
                if row["actionNumber"] in self.reviewed_foul_opponents:
                    # A double foul whose text names nobody: the reviewed other
                    # party, from the opposing roster, as the text would name them.
                    reviewed = self.reviewed_foul_opponents[row["actionNumber"]]
                    if match or self.context.roster.get(reviewed, {}).get("team_id") != opponent:
                        raise V3DecodeError(
                            "Event foul-opponent override does not fit the recorded event"
                        )
                    self._unused_reviewed["foul-opponent"].discard(row["actionNumber"])
                    event["player3_id"] = reviewed
                    self.reviewed_inputs.append(dict(
                        code="reviewed_foul_opponent", event_num=row["actionNumber"],
                        player_id=reviewed,
                    ))
                elif not match or self._resolve(match[1], team) != player:
                    raise V3DecodeError("Double foul requires both recorded participants")
                else:
                    try:
                        event["player3_id"] = self._resolve(match[2], opponent)
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
            elif kind == "Foul" and subtype not in self.fouls_without_fouled_player:
                self.unknown_attribution.append(
                    dict(event_num=row["actionNumber"], role="foul_drawn")
                )
        elif kind == "Rebound":
            if subtype not in REBOUNDS:
                raise V3DecodeError("Unsupported rebound subtype")
        elif kind == "Substitution":
            match = re.fullmatch(r"SUB: (.+) FOR (.+)", row["description"])
            if subtype or not match or self._resolve(match[2], team) != player:
                raise V3DecodeError(
                    "Substitution description contradicts outgoing player"
                )
            incoming = self._resolve(match[1], team)
            if row["actionNumber"] in self.reviewed_substitution_outgoing:
                # V3 names a player already off the floor: the reviewed teammate
                # who left, as V2 records the outgoing player.
                reviewed = self.reviewed_substitution_outgoing[row["actionNumber"]]
                if reviewed in (player, incoming) or self.context.roster.get(
                    reviewed, {}
                ).get("team_id") != team:
                    raise V3DecodeError(
                        "Event substitution-outgoing override does not fit the recorded event"
                    )
                self._unused_reviewed["substitution-outgoing"].discard(row["actionNumber"])
                self.reviewed_inputs.append(dict(
                    code="reviewed_substitution_outgoing", event_num=row["actionNumber"],
                    recorded_player_id=player, player_id=reviewed,
                ))
                event["player1_id"] = reviewed
            event["player2_id"] = incoming
        elif kind == "Jump Ball":
            # Coach-challenge descriptions carry a "(CC) " marker, others never do.
            marker = r"\(CC\) " if subtype == "Coach Challenge" else ""
            match = re.fullmatch(
                r"Jump Ball " + marker + r"(.+) vs\. (.+): Tip to (.+)",
                row["description"],
            )
            if subtype not in JUMP_BALLS or (
                match and self._resolve(match[1], team) != player
            ):
                raise V3DecodeError(
                    "Jump ball requires explicit resolvable participant roles"
                )
            opponent = next(t for t in self.context.team_ids if t != team)
            try:
                if not match:
                    # A team-won jump ball's V3 description is blank.
                    raise V3DecodeError(
                        "Jump ball requires explicit resolvable participant roles"
                    )
                jumper = self._resolve(match[2], opponent)
                recipient = self._resolve(
                    match[3],
                    active_players=active_players,
                    event_num=row["actionNumber"],
                )
                recipient_team = self.context.roster[recipient]["team_id"]
            except V3DecodeError as error:
                if row["actionNumber"] in self.reviewed_v2_jump_balls:
                    jumper, recipient, recipient_team = self._reviewed_v2_jump_ball(
                        row, opponent, match
                    )
                elif self.live_jump_balls is None:
                    raise V3JumpBallEvidenceRequired(
                        str(error), url=live_play_by_play_url(self.context.game_id)
                    ) from error
                else:
                    jumper, recipient, recipient_team = self._recorded_jump_ball(
                        row, opponent, match
                    )
            # The tip's winner is the recipient's team, or the team that
            # recovered it when no player did.
            event.update(
                team_id=recipient_team or recipient,
                player2_id=recipient if recipient_team else None,
                player3_id=jumper,
            )
        elif not (
            kind == "period" and subtype in ("start", "end")
            or kind == "Timeout" and subtype in self.timeouts
            or kind == "Instant Replay" and subtype in REPLAYS
            or kind == "Ejection" and subtype in EJECTIONS
        ):
            raise V3DecodeError(
                "Unsupported event type/subtype {!r}/{!r}".format(kind, subtype)
            )
        if event["team_id"] is None and kind != "Instant Replay":
            # As the original reads an event with no team: its person, a coach
            # or no one, stands as its team. A replay keeps no team.
            event["team_id"], event["player1_id"] = event["player1_id"], 0
        return event

    def _recorded_jump_ball(self, row, opponent, match):
        """Jump-ball facts V3 omits, from the live action with the same number.

        The live feed records both jumpers' IDs and the recovering player's, or
        no recovering player and the team in possession. Its clock can differ
        for an opening tip, so the action number, period and the V3 jumper's
        personId identify the action. Every fact V3 itself records must agree.
        """
        number, basis = row["actionNumber"], "live action number"
        if number in self.reviewed_live_numbers:
            # Review matched this V3 jump ball to a live action renumbered apart.
            if number in self.live_jump_balls:
                raise V3DecodeError("Event live-number override does not fit the recorded event")
            self._unused_reviewed["live-number"].discard(number)
            number, basis = self.reviewed_live_numbers[number], "reviewed live action number"
        found = self.live_jump_balls.get(number, [])
        live = found[0] if len(found) == 1 else {}
        team_descriptor = (
            "personId" not in live
            and live.get("descriptor") == "team"
            and "jumpBallRecoverdPersonId" not in live
            and live.get("jumpBallRecoveredName") == "Team ({})".format(live.get("teamTricode"))
        )
        if team_descriptor:
            # NBA 2026-27's live feed records a team recovery with no person:
            # descriptor "team", the recovering team as the action's team and as
            # the recovered name, where 2023-24 to 2025-26 record personId 0.
            live = dict(live, personId=0)
        recovered = live.get("jumpBallRecoverdPersonId")
        if (
            any(type(live.get(key)) is not int for key in LIVE_JUMP_BALL_FIELDS)
            or (recovered is not None and type(recovered) is not int)
            or live["period"] != row["period"]
        ):
            raise V3DecodeError("Recorded live play-by-play lacks this jump ball")
        # The live "possession" field can already reflect a held-ball turnover
        # recorded next; a recovering team is the action's team.
        player, jumper, recipient, recipient_team = self._jump_ball_roles(
            row,
            opponent,
            match,
            [live.get("jumpBallWonPersonId"), live.get("jumpBallLostPersonId")],
            recovered,
            None if live["personId"] else live["teamId"],
            "Recorded live",
        )
        self.recorded_jump_balls.append(
            dict(
                code="recorded_live_jump_ball",
                event_num=row["actionNumber"],
                jumpers=[player, jumper],
                recipient=recipient,
                team_recovery=recipient_team is None,
                basis=basis + ", period and V3 jumper personId",
                **({} if number == row["actionNumber"] else dict(live_action_number=number)),
                **(dict(live_format="2026-27 team recovery") if team_descriptor else {}),
            )
        )
        return jumper, recipient, recipient_team

    def _reviewed_v2_jump_ball(self, row, opponent, match):
        """Jump-ball facts V3 omits, from the reviewed V2 export row of a game
        the live feed does not record.

        V2 records both jumpers as PLAYER1/PLAYER2 and the recovering player,
        or for a team recovery the team, as PLAYER3. The row must be this
        event's: the same event number, period and whole-second clock. Every
        fact V3 itself records must agree, as with the live feed.
        """
        v2 = self.reviewed_v2_jump_balls[row["actionNumber"]]
        minutes, seconds = CLOCK.fullmatch(row["clock"]).groups()
        if (
            v2["EVENTMSGTYPE"] != 10
            or v2["EVENTNUM"] != row["actionNumber"]
            or v2["PERIOD"] != row["period"]
            or v2["PCTIMESTRING"] != "{}:{:02d}".format(int(minutes), int(Decimal(seconds)))
            or v2["PERSON1TYPE"] not in V2_PLAYER_TYPES
            or v2["PERSON2TYPE"] not in V2_PLAYER_TYPES
            or v2["PERSON3TYPE"] not in V2_PLAYER_TYPES + V2_TEAM_TYPES
        ):
            raise V3DecodeError("Event v2-jump-ball override does not fit the recorded event")
        self._unused_reviewed["v2-jump-ball"].discard(row["actionNumber"])
        team_recovery = v2["PERSON3TYPE"] in V2_TEAM_TYPES
        player, jumper, recipient, recipient_team = self._jump_ball_roles(
            row,
            opponent,
            match,
            [v2["PLAYER1_ID"], v2["PLAYER2_ID"]],
            None if team_recovery else v2["PLAYER3_ID"],
            v2["PLAYER3_ID"] if team_recovery else None,
            "Reviewed V2 export",
        )
        self.reviewed_inputs.append(
            dict(
                code="reviewed_v2_jump_ball",
                event_num=row["actionNumber"],
                jumpers=[player, jumper],
                recipient=recipient,
                team_recovery=team_recovery,
                basis="V2 event number, period and clock, and V3 jumper personId",
            )
        )
        return jumper, recipient, recipient_team

    def _jump_ball_roles(self, row, opponent, match, jumpers, recovered, winner, source):
        """The V3 jumper's opponent and the recipient, from recorded jump-ball facts.

        ``jumpers`` are both jumpers' IDs, ``recovered`` the recovering player's
        or None, and ``winner`` the recovering team when no player recovered.
        """
        player = row["personId"]
        if jumpers.count(player) != 1:
            raise V3DecodeError(source + " jumpers disagree with the V3 jumper")
        jumper = jumpers[1 - jumpers.index(player)]
        if self.context.roster.get(jumper, {}).get("team_id") != opponent or (
            match and jumper not in self._candidates(match[2], opponent)
        ):
            raise V3DecodeError(source + " opposing jumper disagrees with V3")
        if recovered:
            if recovered not in self.context.roster or (
                match and recovered not in self._candidates(match[3])
            ):
                raise V3DecodeError(source + " tip recipient disagrees with V3")
            return player, jumper, recovered, self.context.roster[recovered]["team_id"]
        if match or winner not in self.context.team_ids:
            raise V3DecodeError(source + " team recovery is not explicit")
        return player, jumper, winner, None

    def _technical_free_throw_opponent(self, row):
        # The team that did not shoot the technical free throw at the row's
        # period and clock, with the other rows recorded there.
        if not self.context.game_id.startswith("00"):
            raise V3DecodeError("Event requires a known team")
        same_time = [
            source for source in self.raw_rows
            if source is not row
            and (source["period"], source["clock"]) == (row["period"], row["clock"])
        ]
        shooters = {
            self.context.roster.get(source["personId"], {}).get("team_id")
            for source in same_time
            if source["actionType"] == "Free Throw"
            and source["subType"] == "Free Throw Technical"
        }
        if len(shooters) != 1 or not shooters <= set(self.context.team_ids):
            raise V3DecodeError(
                "Team technical requires one recorded technical free-throw team"
            )
        return next(t for t in self.context.team_ids if t not in shooters), same_time

    def _teamless_excess_timeout_team(self, row):
        # The team charged is the one that did not shoot the technical free
        # throw at the event's period and clock. An excess timeout technical
        # or turnover recorded there with its team must be that team's.
        team, same_time = self._technical_free_throw_opponent(row)
        witnesses = [
            source for source in same_time
            if source["actionType"] in ("Foul", "Turnover")
            and source["subType"] in EXCESS_TIMEOUTS
            and (source["teamId"] or source["personId"])
        ]
        if any(
            (source["teamId"] or source["personId"]) != team for source in witnesses
        ):
            raise V3DecodeError("Excess timeout team contradicts its recorded technical or turnover")
        self.team_technicals.append(
            dict(
                code=TEAMLESS_EXCESS_TIMEOUT_VERSION,
                event_num=row["actionNumber"],
                team_id=team,
                basis="opponent_of_technical_free_throw_shooter",
                recorded_team_events=sorted(s["actionNumber"] for s in witnesses),
            )
        )
        return team

    def _teamless_technical_team(self, row):
        # The team charged is the one that did not shoot the technical free
        # throw at the technical's period and clock. A delay-of-game violation
        # recorded there must be that team's: both teams can delay at once (a
        # warning for one, a technical for the other), so it alone cannot decide.
        team, same_time = self._technical_free_throw_opponent(row)
        violations = [
            source for source in same_time
            if source["actionType"] == "Violation" and source["subType"] == "Delay Of Game"
        ]
        if any((source["teamId"] or source["personId"]) != team for source in violations):
            raise V3DecodeError("Team technical contradicts a recorded delay-of-game violation")
        self.team_technicals.append(
            dict(
                code=TEAMLESS_TECHNICAL_VERSION,
                event_num=row["actionNumber"],
                team_id=team,
                basis="opponent_of_technical_free_throw_shooter",
                delay_of_game_violations=sorted(s["actionNumber"] for s in violations),
            )
        )
        return team

    def _same_clock(self, row, kind, team):
        # A team foul or turnover can name the team as its person, with teamId 0.
        return [
            source for source in self.raw_rows
            if source is not row
            and (source["period"], source["clock"]) == (row["period"], row["clock"])
            and source["actionType"] == kind
            and (
                source["personId"] if source["personId"] in self.context.team_ids
                else self.context.roster.get(source["personId"], {}).get("team_id")
                or source["teamId"]
            ) == team
        ]

    def _technical_free_throw(self, row, team):
        # A technical-type foul awards one technical free throw. A lone "1 of
        # 1" where the other team's only foul at that period and clock is one
        # can be no other free throw.
        if not self.context.game_id.startswith("00"):
            return False
        opponent = next(t for t in self.context.team_ids if t != team)
        fouls = self._same_clock(row, "Foul", opponent)
        if (
            len(fouls) != 1
            or fouls[0]["subType"] not in TECHNICAL_FREE_THROW_FOULS
            or self._same_clock(row, "Free Throw", team)
        ):
            return False
        self.label_rules.append(dict(
            code=TECHNICAL_FREE_THROW_VERSION, event_num=row["actionNumber"],
            foul_event_num=fouls[0]["actionNumber"], foul=fouls[0]["subType"],
            recorded=row["subType"], decoded="Free Throw Technical",
        ))
        return True

    def _transition_take_foul(self, row, team):
        # A transition take foul awards one free throw whatever the team fouls;
        # a personal take foul awards none, or two in the penalty. A take foul
        # outside the penalty, the team's only foul at that period and clock,
        # with one "1 of 1" for the other team there, is a transition take foul.
        if not self.context.game_id.startswith("00") or not TEAM_FOUL_COUNT.search(
            row["description"]
        ):
            return False
        opponent = next(t for t in self.context.team_ids if t != team)
        free_throws = self._same_clock(row, "Free Throw", opponent)
        if self._same_clock(row, "Foul", team) or [
            f["subType"] for f in free_throws
        ] != ["Free Throw 1 of 1"]:
            return False
        self.label_rules.append(dict(
            code=TRANSITION_TAKE_FOUL_VERSION, event_num=row["actionNumber"],
            free_throw_event_num=free_throws[0]["actionNumber"], recorded=row["subType"],
            decoded="Transition Take",
        ))
        return True

    def _blank_flagrant_free_throw(self, row, team):
        # A free throw with neither category nor numbering, in subtype or text,
        # in one shooter's trip of such free throws, where the other team's only
        # foul at that period and clock is a flagrant 1: the trip's attempt, in
        # recorded order, of as many as the trip records.
        if not self.context.game_id.startswith("00"):
            return False
        blank = r"(?:MISS )?.+ Free Throw(?: \(\d+ PTS\))?"
        opponent = next(t for t in self.context.team_ids if t != team)
        fouls = self._same_clock(row, "Foul", opponent)
        trip = [row] + self._same_clock(row, "Free Throw", team)
        trip.sort(key=lambda source: next(
            i for i, recorded in enumerate(self.raw_rows) if recorded is source
        ))
        attempt, total = trip.index(row) + 1, len(trip)
        if (
            [foul["subType"] for foul in fouls] != ["Flagrant Type 1"]
            or any(
                source["subType"] or source["personId"] != row["personId"]
                or not re.fullmatch(blank, source["description"])
                for source in trip
            )
            or (attempt, total) not in FREE_THROWS
        ):
            return False
        self.label_rules.append(dict(
            code=BLANK_FLAGRANT_FREE_THROW_VERSION, event_num=row["actionNumber"],
            foul_event_num=fouls[0]["actionNumber"], recorded="",
            decoded="Free Throw Flagrant {} of {}".format(attempt, total),
        ))
        return True

    def _voided_second_free_throw(self, row, team):
        # A made 1 of 1, the team's only free throw at its period and clock,
        # where the other team's only foul there is a shooting foul, followed by
        # the team's lane violation or offensive goaltending turnover there,
        # with no basket by the team at that clock or the two seconds before it:
        # the first of the two free throws a missed shot's foul awards.
        if not self.context.game_id.startswith("00") or row["description"].startswith("MISS "):
            return False
        opponent = next(t for t in self.context.team_ids if t != team)
        fouls = self._same_clock(row, "Foul", opponent)
        turnovers = [
            source for source in self._same_clock(row, "Turnover", team)
            if source["subType"] in VOIDING_TURNOVERS
        ]
        position = {id(source): i for i, source in enumerate(self.raw_rows)}
        clock = v3_clock_seconds(row["clock"])
        if (
            [foul["subType"] for foul in fouls] != ["Shooting"]
            or self._same_clock(row, "Free Throw", team)
            or len(turnovers) != 1
            or position[id(turnovers[0])] < position[id(row)]
            or any(
                source["actionType"] == "Made Shot"
                and source["period"] == row["period"]
                and self.context.roster.get(source["personId"], {}).get("team_id") == team
                and 0 <= v3_clock_seconds(source["clock"]) - clock <= 2
                for source in self.raw_rows
            )
        ):
            return False
        self.label_rules.append(dict(
            code=VOIDED_SECOND_FREE_THROW_VERSION, event_num=row["actionNumber"],
            foul_event_num=fouls[0]["actionNumber"],
            turnover_event_num=turnovers[0]["actionNumber"],
            recorded="Free Throw 1 of 1", decoded="Free Throw 1 of 2",
        ))
        return True

    def _team_heave_team(self, row):
        from pbpstats.resources.enhanced_pbp.stats_nba_v3.team_heave import (
            TEAM_HEAVE_VERSION,
        )

        # Trust the feed's explicit classification; do not reclassify player shots
        # using distance/time thresholds or infer who attempted the shot. Team
        # heaves are recorded NBA facts from 2025-26; WNBA has no such evidence.
        if (
            not self.context.game_id.startswith("00")
            or int(self.context.game_id[3:5]) < 25
            or row["subType"] != "Team Field Goal Attempt"
            or row["personId"] != 0
            or any(type(row.get(k)) is not int or row[k] != 0
                   for k in ("isFieldGoal", "shotValue", "shotDistance", "xLegacy", "yLegacy"))
            or row.get("shotResult") != ""
            or any(row.get(k) for k in ("playerName", "playerNameI"))
        ):
            raise V3DecodeError("Unsupported or conflicting team-heave facts")
        location, basis = row.get("location"), "explicit_source_teamId_and_location"
        if row["actionNumber"] in self.reviewed_locations:
            if location:
                raise V3DecodeError("Event location override does not fit the recorded event")
            self._unused_reviewed["location"].discard(row["actionNumber"])
            location = self.reviewed_locations[row["actionNumber"]]
            basis = "reviewed_location"
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
            basis=basis,
        )
        return team
