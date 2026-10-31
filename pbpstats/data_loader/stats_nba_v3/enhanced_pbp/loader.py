"""
``StatsNbaV3EnhancedPbpLoader`` loads play-by-play V3 data for a game and
creates :obj:`~pbpstats.resources.enhanced_pbp.enhanced_pbp_item.EnhancedPbpItem` objects
for each event, with native V3 event classes

Enhanced data for each event includes current players on floor, score, fouls to give and number of fouls committed by each player,
plus additional data depending on event type, as the original enhances V2 events

The following code will load pbp data for game id "0022500001" from files located in subdirectories of the /data directory

.. code-block:: python

    from pbpstats.data_loader import StatsNbaV3EnhancedPbpFileLoader, StatsNbaV3EnhancedPbpLoader

    source_loader = StatsNbaV3EnhancedPbpFileLoader("/data")
    pbp_loader = StatsNbaV3EnhancedPbpLoader("0022500001", source_loader)
    print(pbp_loader.items[0].data)  # prints dict with the first event of the game
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math

from pbpstats.data_loader.nba_enhanced_pbp_loader import NbaEnhancedPbpLoader
from pbpstats.data_loader.stats_nba_v3.boxscore.loader import StatsNbaV3BoxscoreLoader
from pbpstats.data_loader.stats_nba_v3.decoder import (
    FOULS,
    FREE_THROWS,
    REBOUNDS,
    TECHNICAL_FOULS,
    TEAM_TURNOVERS,
    TURNOVERS,
    VIOLATIONS,
    DecodedV3,
    V3Context,
    V3DecodeError,
    V3JumpBallEvidenceRequired,
    clock_text,
)
from pbpstats.data_loader.stats_nba_v3.jump_balls import V3JumpBallEvidence
from pbpstats.data_loader.stats_nba_v3.names import (
    add_actor_aliases,
    add_unaccented_names,
    require,
)
from pbpstats.data_loader.stats_nba_v3.overrides import (
    CHANGE_EVENTS,
    EVENT_BLOCK_REMOVALS,
    EVENT_BLOCKS,
    EVENT_CLOCK_RESETS,
    EVENT_CLOCKS,
    EVENT_DUPLICATES,
    EVENT_FOUL_OPPONENTS,
    EVENT_FREE_THROW_SUBTYPES,
    EVENT_LIVE_NUMBERS,
    EVENT_LOCATIONS,
    EVENT_MOVES,
    EVENT_ORDER,
    EVENT_REMOVALS,
    EVENT_SUBSTITUTION_OUTGOING,
    EVENT_SUBTYPES,
    EVENT_TEAMS,
    EVENT_TIP_RECIPIENTS,
    EVENT_TURNOVERS,
    EVENT_V2_JUMP_BALLS,
    KEEP_EVENTS,
    STARTERS,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import StatsNbaV3PbpLoader
from pbpstats.data_loader.stats_nba_v3.starters import (
    StarterRecovery,
    V3EvidenceRequired,
    V3StarterBoxscore,
)
from pbpstats.resources.enhanced_pbp import FieldGoal
from pbpstats.resources.enhanced_pbp.rebound import EventOrderError
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_factory import (
    StatsNbaV3EnhancedPbpFactory,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.held_ball import is_candidate_at
from pbpstats.resources.enhanced_pbp.stats_nba_v3.jump_ball import V3HeldBallJumpBall
from pbpstats.resources.enhanced_pbp.stats_nba_v3.team_heave import V3TeamHeave


# NBA V3 records an and-one's basket, foul and free throw at one clock: from
# 2018-19 to 2025-26, 44,766 of the 44,772 baskets followed, past substitutions,
# timeouts and replays, by the other team's shooting or shooting block foul and
# the shooter's lone 1 of 1 at the foul's clock, or by its loose ball foul and a
# teammate's. The other six, as do 30 of 5,460 in 2017-18 and 5 of the first
# 142 in 2026-27, record the basket up to two seconds before the foul. The original
# decides an and-one from the events at the basket's clock alone, so a basket
# recorded early ends the possession before its free throw.
AND_ONE_CLOCK_VERSION = "nba_and_one_clock_v1"
AND_ONE_FOULS = ("Shooting", "Shooting Block", "Loose Ball")
# Rows a basket's foul can follow: substitutions, timeouts and replays.
DEAD_BALL_ACTIONS = ("Substitution", "Timeout", "Instant Replay")
# The missed shots the original's order repairs look for, its V2 event type 2.
MISSED_SHOTS = ("Missed Shot", "Heave")


def clock_seconds(text):
    """Seconds left in the period on an original "M:SS" clock."""
    minutes, _, rest = text.partition(":")
    return Decimal(minutes) * 60 + Decimal(rest)


# The subtype labels a reviewed correction may give each kind of event. Free
# throws are the numbered regular ones only.
SUBTYPE_LABELS = {
    "Free Throw": {"Free Throw {} of {}".format(*numbers) for numbers in FREE_THROWS},
    "Rebound": set(REBOUNDS),
    "Turnover": set(TURNOVERS),
    "Foul": set(FOULS),
    "Violation": set(VIOLATIONS),
}


def reviewed_entries(overrides, name, game_id, empty):
    """One game's entries in a decoded reviewed-correction file."""
    games = overrides.get(name, {})
    return games.get(game_id, games.get(int(game_id), empty))


def load_boxscore(game_id, source_loader):
    """The game's box score loader; a malformed response is a decode rejection."""
    try:
        return StatsNbaV3BoxscoreLoader(game_id, source_loader)
    except V3DecodeError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise V3DecodeError("Unexpected box score or play-by-play response") from error


def boxscore_context(game_id, pbp_bytes, boxscore, source, aliases=None):
    """Teams and the named roster from the official box score, bound to the PBP.

    Names come from the box score's players, the play-by-play's own ID-bound
    actor names and descriptions, and unaccented variants; nobody is guessed
    from a name. ``aliases`` maps a box-score person ID to reviewed extra
    names, for descriptions that use a name the box score does not (for
    example a given name). Period starters are left to the original's
    inference.
    """
    try:
        rows = json.loads(pbp_bytes)["game"]["actions"]
    except (ValueError, KeyError, TypeError) as error:
        raise V3DecodeError("Unexpected box score or play-by-play response") from error
    roster = {}
    for player in boxscore.items:
        if not hasattr(player, "player_id"):
            continue  # a team's totals
        first = getattr(player, "firstName", None)
        family = getattr(player, "familyName", None)
        names = [family, getattr(player, "nameI", None)]
        if first and family:
            names.append(first + " " + family)
        roster[player.player_id] = {
            "team_id": player.team_id,
            "names": sorted({n for n in names if n}),
        }
    for row in rows:
        facts = roster.get(row.get("personId"))
        if facts is None:
            continue
        require(
            row.get("teamId") in (0, facts["team_id"]),
            "roster_identity",
            "Play-by-play actor contradicts the box score team",
        )
        for key in ("playerName", "playerNameI"):
            name = row.get(key)
            if isinstance(name, str) and name.strip() and name not in facts["names"]:
                facts["names"].append(name)
    for identity, names in (aliases or {}).items():
        require(identity in roster, "alias", "Alias for a player not in the box score")
        roster[identity]["names"] += [
            n for n in names if n not in roster[identity]["names"]
        ]
    add_actor_aliases(rows, roster)
    add_unaccented_names(roster)
    teams = (boxscore.home_team_id, boxscore.away_team_id)
    return V3Context(
        game_id, teams, roster, {}, source, hashlib.sha256(pbp_bytes).hexdigest()
    )


def boxscore_starters(boxscore):
    """First-period starters marked in the box score, when each team has five."""
    starters = {boxscore.home_team_id: [], boxscore.away_team_id: []}
    for player in boxscore.items:
        if hasattr(player, "player_id") and getattr(player, "position", None):
            starters[player.team_id].append(player.player_id)
    return starters if all(len(p) == 5 for p in starters.values()) else None


def with_evidence(load, context, fetch_boxscore=None, fetch_live=None):
    """``load(starter_boxscores, jump_balls)``, given the evidence it asks for.

    When the original's starter inference falls back to its period-start box
    score request, ``fetch_boxscore(period, url, params)`` must return that
    response; it is recorded as V3StarterBoxscore evidence. Without it, the
    V3EvidenceRequired error names the exact request instead. A jump ball V3
    leaves undecided likewise needs ``fetch_live(url)`` to return the live
    play-by-play, recorded as V3JumpBallEvidence.
    """
    boxscores, jump_balls = {}, None
    while True:
        try:
            return load(boxscores, jump_balls)
        except V3JumpBallEvidenceRequired as needed:
            if fetch_live is None or jump_balls is not None:
                raise
            response = fetch_live(needed.url)
            jump_balls = V3JumpBallEvidence(
                response.content, response.url, context.pbp_sha256
            )
        except V3EvidenceRequired as needed:
            if fetch_boxscore is None or needed.period in boxscores:
                raise
            response = fetch_boxscore(needed.period, needed.url, needed.params)
            boxscores[needed.period] = V3StarterBoxscore(
                response.content,
                response.url,
                context.pbp_sha256,
                needed.params,
                response.status_code,
                response.reason or "",
            )


class StatsNbaV3EnhancedPbpLoader(StatsNbaV3PbpLoader, NbaEnhancedPbpLoader):
    """
    Loads stats.nba.com source play-by-play V3 data for game.
    Events are stored in items attribute as :obj:`~pbpstats.resources.enhanced_pbp.enhanced_pbp_item.EnhancedPbpItem` objects

    The game's context comes from its box score: the teams, and each player's
    names. Reviewed corrections apply only to the play-by-play bytes they were
    reviewed against. Then the rows the decoder names by role get the reviewed
    corrections, the original's order repairs, linking and enhancement.

    :param str game_id: NBA Stats Game Id
    :param source_loader: :obj:`~pbpstats.data_loader.stats_nba_v3.enhanced_pbp.file.StatsNbaV3EnhancedPbpFileLoader` or :obj:`~pbpstats.data_loader.stats_nba_v3.enhanced_pbp.web.StatsNbaV3EnhancedPbpWebLoader` object
    :raises: :obj:`~pbpstats.data_loader.stats_nba_v3.decoder.V3DecodeError`:
        If the play-by-play cannot be decoded as recorded, or recorded evidence it needs is missing.
    """

    data_provider = "stats_nba_v3"
    resource = "EnhancedPbp"
    parent_object = "Game"

    def __init__(self, game_id, source_loader):
        self.source_loader = source_loader
        super().__init__(game_id, source_loader)

    @classmethod
    def from_context(cls, source_bytes, context, **options):
        """Events from recorded V3 bytes and a given game context, with no I/O.

        ``options`` are ``validate_source_order``, reviewed ``overrides``, and
        recorded ``event_order``, ``starter_boxscores`` and ``jump_balls``
        evidence; a parse that needs evidence it is not given raises the error
        naming it.
        """
        loader = cls.__new__(cls)
        loader.source_data = source_bytes
        loader.file_directory = None
        loader._load(context, **options)
        return loader

    def _make_pbp_items(self):
        """
        makes the events from the play-by-play, in the context its box score
        gives, asking the source loader for the evidence the parse needs
        """
        source_loader = self.source_loader
        overrides = source_loader.load_overrides(self.game_id, self.source_data)
        boxscore = load_boxscore(self.game_id, source_loader.boxscore_source_loader)
        context = boxscore_context(
            self.game_id,
            self.source_data,
            boxscore,
            source_loader.source,
            source_loader.load_aliases(boxscore),
        )

        def parse(fetch_live=None):
            with_evidence(
                lambda boxscores, jump_balls: self._load(
                    context,
                    overrides=overrides,
                    starter_boxscores=boxscores,
                    jump_balls=jump_balls,
                ),
                context,
                source_loader.load_starter_boxscore,
                fetch_live,
            )

        # Starters come from the original's own inference. Only if a name is
        # ambiguous, such as a tip to one of two same-named players, are the
        # box score's first-period starter markers supplied as recorded
        # on-court evidence; the possession loader checks each such resolution
        # against the original's lineup, and the context then lists those
        # starters. A jump ball that stays undecided, including a team-won
        # one, is completed from the live play-by-play.
        try:
            parse()
        except V3DecodeError as error:
            starters = boxscore_starters(boxscore)
            if "is unresolved or ambiguous" in str(error) and starters is not None:
                context.period_starters = {1: starters}
                try:
                    return parse()
                except V3JumpBallEvidenceRequired:
                    if source_loader.load_live is None:
                        raise
            elif source_loader.load_live is None or not isinstance(
                error, V3JumpBallEvidenceRequired
            ):
                raise
            parse(source_loader.load_live)

    def _load(
        self,
        context,
        *,
        validate_source_order=True,
        overrides=None,
        event_order=None,
        starter_boxscores=None,
        jump_balls=None,
    ):
        self.overrides, self.override_diagnostics = (
            overrides.decode(self.source_data) if overrides is not None else ({}, [])
        )
        decoded = DecodedV3(
            self.source_data,
            context,
            jump_balls,
            locations=reviewed_entries(
                self.overrides, EVENT_LOCATIONS, context.game_id, {}
            ),
            live_numbers=reviewed_entries(
                self.overrides, EVENT_LIVE_NUMBERS, context.game_id, {}
            ),
            teams=reviewed_entries(self.overrides, EVENT_TEAMS, context.game_id, {}),
            foul_opponents=reviewed_entries(
                self.overrides, EVENT_FOUL_OPPONENTS, context.game_id, {}
            ),
            removed=reviewed_entries(self.overrides, EVENT_REMOVALS, context.game_id, {}),
            block_removals=reviewed_entries(
                self.overrides, EVENT_BLOCK_REMOVALS, context.game_id, []
            ),
            v2_jump_balls=reviewed_entries(
                self.overrides, EVENT_V2_JUMP_BALLS, context.game_id, {}
            ),
            free_throw_subtypes=reviewed_entries(
                self.overrides, EVENT_FREE_THROW_SUBTYPES, context.game_id, {}
            ),
            substitution_outgoing=reviewed_entries(
                self.overrides, EVENT_SUBSTITUTION_OUTGOING, context.game_id, {}
            ),
        )
        self.decoded = decoded
        self.game_id = context.game_id
        self.recorded_event_order = (
            event_order.decode(decoded) if event_order is not None else None
        )
        starter_boxscores = (
            deepcopy(starter_boxscores) if starter_boxscores is not None else {}
        )
        if not isinstance(starter_boxscores, dict) or any(
            type(p) is not int or p < 1 for p in starter_boxscores
        ):
            raise V3DecodeError(
                "Starter boxscores must be keyed by positive period numbers"
            )
        for evidence in starter_boxscores.values():
            evidence.validate(self.source_data, context.game_id)
        self.starter_boxscores = starter_boxscores
        self.repairs = []
        # The rows corrections and order repairs edit, as the original edits
        # its play-by-play file; decoded.projected stays as decoded.
        fields = list(decoded.projected[0])
        self.data = [{key: row.get(key) for key in fields} for row in decoded.projected]
        self._apply_reviewed_duplicates()
        self._apply_reviewed_removals()
        self._apply_reviewed_blocks()
        self._apply_reviewed_tip_recipients()
        self._apply_reviewed_subtypes()
        self._apply_reviewed_clocks()
        self._apply_reviewed_moves()
        self._apply_and_one_clocks()
        self.added_rows = self._apply_reviewed_turnovers()
        self.clock_resets = self._apply_reviewed_clock_resets()
        self._apply_reviewed_event_order()
        if validate_source_order:
            self._make_events()
        else:
            self.factory = StatsNbaV3EnhancedPbpFactory()
            self.items = [
                self.factory.get_event_class(row)(row, index)
                for index, row in enumerate(self.data)
            ]
            self._add_extra_attrs_to_all_events()
            self._add_shot_x_y_coords()
        dropped = {
            **self._reviewed_entries(EVENT_DUPLICATES, {}),
            **self._reviewed_entries(EVENT_REMOVALS, {}),
        }
        for event in self.items:
            event.reviewed_clock_reset = self.clock_resets.get(event.event_num)
            if event.event_num in self.added_rows:
                # A reviewed event that V3 does not record owns no recorded row.
                event.v3_source_indices = ()
                event.v3_source_row = deepcopy(self.added_rows[event.event_num])
                continue
            group = decoded.groups[event.event_num]
            indices = group["source_indices"]
            copies = [copy for copy, kept in sorted(dropped.items()) if kept == event.event_num]
            if copies:
                # A dropped copy's or removed event's recorded rows belong to
                # the event kept, so every recorded row still belongs to
                # exactly one event.
                indices = tuple(sorted(indices + tuple(
                    i for copy in copies for i in decoded.groups[copy]["source_indices"]
                )))
            event.v3_source_indices = indices
            event.v3_source_row = deepcopy(group["primary"])

    def _make_events(self):
        # The original's _make_pbp_items, on the corrected rows.
        self._fix_order_when_technical_foul_before_period_start()
        self.factory = StatsNbaV3EnhancedPbpFactory()
        self.items = [
            self.factory.get_event_class(item)(item, i)
            for i, item in enumerate(self.data)
        ]
        self._add_extra_attrs_to_all_events()
        self._check_rebound_event_order(6)
        self._add_shot_x_y_coords()

    def _check_rebound_event_order(self, max_retries):
        # The original's: while a rebound does not follow its missed shot, fix
        # the common order errors, then fall back to the provider's order.
        attempts = 0
        while attempts <= max_retries:
            try:
                for event in self.items:
                    if hasattr(event, "missed_shot"):
                        event.missed_shot
                break
            except EventOrderError as e:
                self._fix_common_event_order_error(e)
                self.items = [
                    self.factory.get_event_class(item)(item, i)
                    for i, item in enumerate(self.data)
                ]
                self._add_extra_attrs_to_all_events()
                attempts += 1
        try:
            for event in self.items:
                if hasattr(event, "missed_shot"):
                    event.missed_shot
        except EventOrderError:
            self._use_data_nba_event_order()
            self.items = [
                self.factory.get_event_class(item)(item, i)
                for i, item in enumerate(self.data)
            ]
            self._add_extra_attrs_to_all_events()

    def _fix_order_when_technical_foul_before_period_start(self):
        # The original's: a technical foul recorded before its period's start
        # puts each period's start first, for periods 1 to 10.
        def is_start(row):
            return (row["action_type"], row["sub_type"]) == ("period", "start")

        starts_found, reorder = [], False
        for row in self.data:
            if is_start(row):
                starts_found.append(row["period"])
            if (
                row["action_type"] == "Foul"
                and row["sub_type"] in TECHNICAL_FOULS
                and row["period"] not in starts_found
            ):
                reorder = True
        if not reorder:
            return
        starts, others = {}, {}
        for row in self.data:
            if is_start(row):
                starts[row["period"]] = row
            else:
                others.setdefault(row["period"], []).append(row)
        self.data = [
            row
            for period in range(1, 11)
            for row in ([starts[period]] if period in starts else []) + others.get(period, [])
        ]
        self._save_data_to_file()

    def _fix_common_event_order_error(self, exception):
        # The original's fixes for a rebound that does not follow its missed
        # shot, found from the event number in the error:
        # - subs/timeouts between free throws being between missed second FT and rebound
        # - end of period replay events being between missed shot and rebound
        # - rebound and shot in reverse order
        # - shot, rebound, rebound - first rebound needs to me moved to before shot
        # - shot, rebound, rebound - second rebound needs to be moved ahead of shot and first rebound
        event_num = int(str(exception).split("EventNum: ")[-1].split(">")[0])
        rows = self.data
        for i, row in enumerate(rows):
            if row["event_num"] == event_num:
                issue_event_index = i

        if rows[issue_event_index]["action_type"] in ["Substitution", "Timeout"]:
            # move all sub/timeout events between ft and rebound to before ft
            row_index = issue_event_index
            while rows[row_index]["action_type"] in ["Substitution", "Timeout"]:
                row_index -= 1
            new_rows = []
            row_to_move_event_num = rows[row_index]["event_num"]
            for row in rows:
                if row["event_num"] == row_to_move_event_num:
                    row_to_move = row
                elif row["event_num"] == event_num:
                    new_rows.append(row)
                    new_rows.append(row_to_move)
                else:
                    new_rows.append(row)
            self.data = new_rows
        elif (
            rows[issue_event_index]["action_type"] == "Instant Replay"
            and rows[issue_event_index + 1]["action_type"] == "Rebound"
        ):
            # move replay event after rebound
            rows[issue_event_index], rows[issue_event_index + 1] = (
                rows[issue_event_index + 1],
                rows[issue_event_index],
            )
        elif (
            rows[issue_event_index + 1]["action_type"] == "Rebound"
            and rows[issue_event_index + 1]["event_num"] == event_num - 1
        ):
            # rebound and shot need to be flipped
            rows[issue_event_index], rows[issue_event_index + 1] = (
                rows[issue_event_index + 1],
                rows[issue_event_index],
            )
        elif (
            rows[issue_event_index + 1]["action_type"] == "Rebound"
            and rows[issue_event_index + 1]["event_num"] == event_num + 2
            and rows[issue_event_index - 1]["action_type"] in MISSED_SHOTS
            and rows[issue_event_index - 1]["event_num"] == event_num + 1
        ):
            # shot, rebound, rebound - first rebound need to me moved to before shot
            rows[issue_event_index - 1], rows[issue_event_index] = (
                rows[issue_event_index],
                rows[issue_event_index - 1],
            )
        elif (
            rows[issue_event_index + 1]["action_type"] == "Rebound"
            and rows[issue_event_index + 1]["event_num"] == event_num - 2
            and rows[issue_event_index - 1]["action_type"] in MISSED_SHOTS
            and rows[issue_event_index - 1]["event_num"] == event_num - 1
        ):
            # shot, rebound, rebound - second rebound needs to be moved ahead of shot and first rebound
            first_rebound = rows[issue_event_index + 1]
            second_rebound = rows[issue_event_index]
            shot_event = rows[issue_event_index - 1]
            rows[issue_event_index + 1] = second_rebound
            rows[issue_event_index] = shot_event
            rows[issue_event_index - 1] = first_rebound

        self._save_data_to_file()

    def _reviewed_entries(self, name, empty):
        return reviewed_entries(self.overrides, name, self.game_id, empty)

    def _apply_reviewed_duplicates(self):
        # Drops an event recorded twice, as editing the play-by-play file would,
        # only when every projected fact but its number matches the copy kept.
        duplicates = self._reviewed_entries(EVENT_DUPLICATES, {})
        by_number = {row["event_num"]: row for row in self.data}

        def facts(row):
            return {key: value for key, value in row.items() if key != "event_num"}

        for event, kept in sorted(duplicates.items()):
            if event not in by_number or kept not in by_number or kept in duplicates:
                raise V3DecodeError("Event duplicate override does not keep a recorded copy")
            if facts(by_number[event]) != facts(by_number[kept]):
                raise V3DecodeError("Event duplicate override names events that differ")
            self.data.remove(by_number[event])
            self.repairs.append(dict(code="reviewed_duplicate_event", event_num=event, kept=kept))

    def _apply_reviewed_removals(self):
        # Drops an event that another recorded event already records, as editing
        # the play-by-play file would: both of one kind and period, with the
        # removed event's actor a person the kept event names.
        removals = self._reviewed_entries(EVENT_REMOVALS, {})
        duplicates = self._reviewed_entries(EVENT_DUPLICATES, {})
        by_number = {row["event_num"]: row for row in self.data}
        for event, kept in sorted(removals.items()):
            row, keeper = by_number.get(event), by_number.get(kept)
            if (
                row is None
                or keeper is None
                or kept in removals
                or kept in duplicates
                or (row["period"], row["action_type"])
                != (keeper["period"], keeper["action_type"])
                or not row["player1_id"]
                or row["player1_id"]
                not in (keeper["player1_id"], keeper["player2_id"], keeper["player3_id"])
            ):
                raise V3DecodeError("Event removal override does not fit the recorded events")
            self.data.remove(row)
            self.repairs.append(dict(code="reviewed_removed_event", event_num=event, kept=kept))

    def _apply_reviewed_blocks(self):
        # Records the blocker V3 omits as the decoder records a block row: as
        # player 3 of a missed field goal, a player on the other team's roster.
        blocks = self._reviewed_entries(EVENT_BLOCKS, {})
        by_number = {row["event_num"]: row for row in self.data}
        roster = self.decoded.context.roster
        for event, player in sorted(blocks.items()):
            row = by_number.get(event)
            if (
                row is None
                or row["action_type"] not in MISSED_SHOTS
                or row["player3_id"] is not None
                or player not in roster
                or roster[player]["team_id"] == row["team_id"]
            ):
                raise V3DecodeError("Event block override does not fit the recorded event")
            row["player3_id"] = player
            self.repairs.append(dict(code="reviewed_event_block", event_num=event, blocker=player))

    def _apply_reviewed_tip_recipients(self):
        # Records who secured a jump ball: the player as player 2, whose team won
        # the tip, or a team that secures it, as when the tip goes out of bounds,
        # as the winning team with no player 2. The description keeps V3's text.
        recipients = self._reviewed_entries(EVENT_TIP_RECIPIENTS, {})
        by_number = {row["event_num"]: row for row in self.data}
        roster = self.decoded.context.roster
        teams = self.decoded.context.team_ids
        for event, player in sorted(recipients.items()):
            row = by_number.get(event)
            if (
                row is None
                or row["action_type"] != "Jump Ball"
                or player not in roster and player not in teams
                or (row["player2_id"] or row["team_id"]) == player
            ):
                raise V3DecodeError("Event tip-recipient override does not fit the recorded event")
            recorded = row["player2_id"] or row["team_id"]
            if player in teams:
                row["team_id"], row["player2_id"] = player, None
            else:
                row["team_id"], row["player2_id"] = roster[player]["team_id"], player
            self.repairs.append(dict(
                code="reviewed_tip_recipient", event_num=event, recorded=recorded, reviewed=player
            ))

    def _apply_reviewed_subtypes(self):
        # Edits the row's action type as the original's remedy of editing the
        # play-by-play file would. A free throw's label in its description
        # follows; other descriptions keep the recorded text.
        labels = self._reviewed_entries(EVENT_SUBTYPES, {})
        by_number = {row["event_num"]: row for row in self.data}
        for event, label in sorted(labels.items()):
            row = by_number.get(event)
            table = SUBTYPE_LABELS.get(row["action_type"]) if row is not None else None
            if table is None or label not in table or row["sub_type"] not in table:
                raise V3DecodeError("Event subtype override does not fit the recorded event")
            recorded, row["sub_type"] = row["sub_type"], label
            if row["action_type"] == "Free Throw":
                row["description"] = row["description"].replace(recorded, label)
            self.repairs.append(dict(
                code="reviewed_event_subtype", event_num=event, recorded=recorded, reviewed=label
            ))

    def _apply_reviewed_clocks(self):
        # At most two seconds from the recorded clock, keeping the recorded order.
        clocks = self._reviewed_entries(EVENT_CLOCKS, {})
        rows = self.data
        index = {row["event_num"]: i for i, row in enumerate(rows)}
        for event, value in sorted(clocks.items()):
            if event not in index:
                raise V3DecodeError("Event clock override names an event not in the source")
            row, new = rows[index[event]], clock_text(value)
            if abs(clock_seconds(new) - clock_seconds(row["clock"])) > 2:
                raise V3DecodeError("Event clock override moves an event more than two seconds")
            recorded, row["clock"] = row["clock"], new
            self.repairs.append(dict(
                code="reviewed_event_clock", event_num=event, recorded=recorded, reviewed=new
            ))
        # Only the edited events' neighbours are checked: a recording can hold
        # inversions elsewhere that the original's own order repairs fix.
        for event in clocks:
            i = index[event]
            for before, after in ((i - 1, i), (i, i + 1)):
                if (
                    0 <= before
                    and after < len(rows)
                    and rows[before]["period"] == rows[after]["period"]
                    and clock_seconds(rows[before]["clock"])
                    < clock_seconds(rows[after]["clock"])
                ):
                    raise V3DecodeError("Event clock override breaks the recorded order")

    def _apply_reviewed_moves(self):
        # Moves an event V3 records at the wrong time to just after another
        # event of its period, taking that event's clock, as editing the
        # play-by-play file would.
        moves = self._reviewed_entries(EVENT_MOVES, {})
        rows = self.data
        for event, after in sorted(moves.items()):
            found = {row["event_num"]: row for row in rows}
            moved, anchor = found.get(event), found.get(after)
            if moved is None or anchor is None or moved["period"] != anchor["period"]:
                raise V3DecodeError("Event move override does not fit the recorded events")
            rows.remove(moved)
            recorded, moved["clock"] = moved["clock"], anchor["clock"]
            rows.insert(rows.index(anchor) + 1, moved)
            self.repairs.append(dict(
                code="reviewed_moved_event", event_num=event, after=after,
                recorded=recorded, reviewed=moved["clock"],
            ))

    def _apply_and_one_clocks(self):
        # A basket recorded up to two seconds before the foul that makes it an
        # and-one takes the foul's clock (AND_ONE_CLOCK_VERSION), after the
        # reviewed clocks and moves. Only substitutions, timeouts and replays,
        # all at the foul's clock, may come between them.
        if not self.game_id.startswith("00"):
            return
        rows = self.data
        for i, shot in enumerate(rows):
            if shot["action_type"] != "Made Shot":
                continue
            j = next(
                (
                    j
                    for j in range(i + 1, len(rows))
                    if rows[j]["action_type"] not in DEAD_BALL_ACTIONS
                ),
                None,
            )
            if j is None:
                continue
            foul = rows[j]
            period, clock, team = foul["period"], foul["clock"], foul["team_id"]
            if (
                foul["action_type"] != "Foul"
                or foul["sub_type"] not in AND_ONE_FOULS
                or period != shot["period"]
                or team in (None, shot["team_id"])
                or not 0 < clock_seconds(shot["clock"]) - clock_seconds(clock) <= 2
                or any(row["clock"] != clock for row in rows[i + 1:j])
            ):
                continue
            at_foul = [r for r in rows if (r["period"], r["clock"]) == (period, clock)]
            fouls = [
                r
                for r in at_foul
                if r["action_type"] == "Foul" and r["team_id"] == team
            ]
            free_throws = [
                r
                for r in at_foul
                if r["action_type"] == "Free Throw"
                and r["team_id"] == shot["team_id"]
            ]
            if (
                len(fouls) != 1
                or len(free_throws) != 1
                or free_throws[0]["sub_type"] != "Free Throw 1 of 1"
                or foul["sub_type"] != "Loose Ball"
                and free_throws[0]["player1_id"] != shot["player1_id"]
            ):
                continue
            recorded, shot["clock"] = shot["clock"], clock
            self.repairs.append(dict(
                code=AND_ONE_CLOCK_VERSION, event_num=shot["event_num"],
                foul_event_num=foul["event_num"], free_throw_event_num=free_throws[0]["event_num"],
                recorded=recorded, decoded=clock,
            ))

    def _apply_reviewed_turnovers(self):
        # Adds a turnover V3 does not record, as the original's remedy of editing
        # the play-by-play file would: a row like the decoder's own, just before
        # another event and at its period and clock. The player may instead be
        # one of the two teams, for a turnover of a kind V3 records as a team's
        # (TEAM_TURNOVERS), shaped as the decoder shapes those: no person, the
        # team as the event's team. Returns each added event's V3-shaped row,
        # which no recorded row backs.
        turnovers = self._reviewed_entries(EVENT_TURNOVERS, {})
        rows = self.data
        index = {row["event_num"]: i for i, row in enumerate(rows)}
        roster = self.decoded.context.roster
        added = {}
        for event, entry in sorted(turnovers.items()):
            before, player, label = entry["before"], entry["player"], entry["subtype"]
            by_team = player in self.decoded.context.team_ids
            if (
                event in index
                or event in self.decoded.groups
                or before not in index
                or not (player in roster or by_team and label in TEAM_TURNOVERS)
                or label not in TURNOVERS
                or label == ""
            ):
                raise V3DecodeError("Event turnover override does not fit the recorded events")
            anchor = rows[index[before]]
            recorded = self.decoded.groups[before]["primary"]
            if by_team:
                team, person, name, description = player, 0, "", label
            else:
                team, person = roster[player]["team_id"], player
                name = next(
                    (r["playerName"] for r in self.decoded.raw_rows
                     if r.get("personId") == player and r.get("playerName")),
                    roster[player]["names"][0],
                )
                description = f"{name} {label}"
            row = dict(
                game_id=anchor["game_id"], event_num=event, period=anchor["period"],
                clock=anchor["clock"], description=description,
                action_type="Turnover", sub_type=label,
                team_id=team, player1_id=person, player2_id=None, player3_id=None,
            )
            rows.insert(index[before], row)
            index = {r["event_num"]: i for i, r in enumerate(rows)}
            added[event] = dict(
                actionNumber=event, clock=recorded["clock"], period=recorded["period"],
                teamId=0 if by_team else team, personId=player, playerName=name,
                description=description, actionType="Turnover", subType=label,
            )
            self.repairs.append(dict(
                code="reviewed_added_turnover", event_num=event, before=before,
                player=player, subtype=label,
            ))
        return added

    def _apply_reviewed_clock_resets(self):
        # The game clock set back to a later time right after an event: the
        # events played after the reset, which V3 sorts among earlier ones by
        # clock, move to follow it in their recorded order. The clock must run
        # down on both sides of the reset. Returns each reset clock by event.
        resets = self._reviewed_entries(EVENT_CLOCK_RESETS, {})
        rows = self.data
        applied = {}
        for event, entry in sorted(resets.items()):
            index = {row["event_num"]: i for i, row in enumerate(rows)}
            moved, reset = entry["events"], clock_text(entry["clock"])
            if (
                event not in index
                or any(n not in index or index[n] > index[event] for n in moved)
                or moved != sorted(moved, key=index.get)
            ):
                raise V3DecodeError("Event clock-reset override does not fit the recorded events")
            anchor, block = rows[index[event]], [rows[index[n]] for n in moved]
            first = index[moved[0]]
            if (
                any(row["period"] != anchor["period"] for row in block)
                or clock_seconds(reset) <= clock_seconds(anchor["clock"])
                or clock_seconds(block[0]["clock"]) > clock_seconds(reset)
            ):
                raise V3DecodeError("Event clock-reset override does not fit the recorded events")
            for row in block:
                rows.remove(row)
            at = rows.index(anchor) + 1
            rows[at:at] = block
            span = rows[max(first - 1, 0):at + len(block) + 1]
            for before, after in zip(span, span[1:]):
                if (
                    before is not anchor
                    and before["period"] == after["period"]
                    and clock_seconds(before["clock"])
                    < clock_seconds(after["clock"])
                ):
                    raise V3DecodeError("Event clock-reset override breaks a running clock")
            applied[event] = reset
            self.repairs.append(dict(
                code="reviewed_clock_reset", event_num=event, clock=reset, moved=list(moved)
            ))
        return applied

    def _apply_reviewed_event_order(self):
        # The original's remedy for events recorded out of order is to edit the
        # play-by-play file. Reviewed moves edit these rows the same way, once,
        # before the events are made.
        moves = self._reviewed_entries(EVENT_ORDER, [])
        if not moves:
            return
        rows = self.data
        for event, before in moves:
            found = {row["event_num"]: row for row in rows}
            if event not in found or before not in found:
                raise V3DecodeError("Event-order override names an event not in the source")
            moved, anchor = found[event], found[before]
            if (moved["period"], moved["clock"]) != (
                anchor["period"], anchor["clock"]
            ):
                raise V3DecodeError("Event-order override moves an event to another clock")
            rows.remove(moved)
            rows.insert(rows.index(anchor), moved)
        self.repairs.append(dict(code="reviewed_event_order", moves=deepcopy(moves)))

    def _load_possession_changing_event_overrides(self):
        self.possession_changing_event_overrides = deepcopy(
            self.overrides.get(CHANGE_EVENTS, {})
        )
        self.non_possession_changing_event_overrides = deepcopy(
            self.overrides.get(KEEP_EVENTS, {})
        )

    def _add_extra_attrs_to_all_events(self):
        # This hook also runs after each original source-order repair rebuild.
        # A jump ball the held-ball rule covers becomes its extension class
        # before linking/enhancement; the rule depends on the events after it,
        # which the factory does not see.
        rows = {r["event_num"]: r for r in self.data}
        self.items = [
            V3HeldBallJumpBall(rows[event.event_num], index)
            if is_candidate_at(self.items, index)
            else event
            for index, event in enumerate(self.items)
        ]
        super()._add_extra_attrs_to_all_events()

    def _set_period_start_items(self):
        # Each original source-order repair rebuilds the events, which runs this
        # again. Keep one starter_recovery result per period, for the final
        # event order; recorded_starter_boxscore entries stay a log of every
        # consumed response, as the original repeats its request per rebuild.
        self.repairs[:] = [
            d for d in self.repairs if d.get("code") != "starter_recovery"
        ]
        for index in self.start_period_indices:
            start = self.items[index]
            start.team_starting_with_ball = start.get_team_starting_with_ball()
            if start.period not in self.decoded.context.period_starters:
                start.period_starters = StarterRecovery(
                    start,
                    self.overrides.get(STARTERS, {}),
                    self.starter_boxscores,
                    self.repairs,
                ).load()
            else:
                start.period_starters = deepcopy(
                    self.decoded.context.period_starters[start.period]
                )

    def _add_shot_x_y_coords(self):
        for event in self.items:
            if not isinstance(event, FieldGoal) or isinstance(event, V3TeamHeave):
                continue
            row = self.decoded.groups[event.event_num]["primary"]
            for source, target in (("xLegacy", "locX"), ("yLegacy", "locY")):
                if source in row and row[source] is not None:
                    value = row[source]
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise V3DecodeError("Shot coordinate must be finite")
                    setattr(event, target, value)

    def _save_data_to_file(self):
        self.repairs.append(
            {
                "code": "legacy_order_repair",
                "event_order": [row["event_num"] for row in self.data],
            }
        )

    def _use_data_nba_event_order(self):
        if self.recorded_event_order is None:
            raise V3DecodeError(
                "Original ordering repair requires additional recorded provider evidence"
            )
        if self.added_rows:
            raise V3DecodeError("Recorded provider order cannot place a reviewed added event")
        order, diagnostic = self.recorded_event_order
        by_number = {row["event_num"]: row for row in self.data}
        # Same ordering as the original provider fallback. Evidence validation
        # additionally prevents its silent dropping/duplication of source rows.
        self.data = [by_number[number] for number in order]
        self.repairs.append(deepcopy(diagnostic))
        self._save_data_to_file()
