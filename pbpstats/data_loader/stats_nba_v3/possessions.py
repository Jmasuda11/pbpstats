"""Offline construction of native V3 events and the original's possessions."""

from collections import Counter
from copy import deepcopy
from decimal import Decimal
import math

from pbpstats import (
    G_LEAGUE_GAME_ID_PREFIX,
    G_LEAGUE_STRING,
    NBA_GAME_ID_PREFIX,
    NBA_STRING,
    WNBA_GAME_ID_PREFIX,
    WNBA_STRING,
)
from pbpstats.data_loader.nba_enhanced_pbp_loader import NbaEnhancedPbpLoader
from pbpstats.data_loader.stats_nba.possessions.loader import StatsNbaPossessionLoader
from pbpstats.resources.enhanced_pbp import FieldGoal, Substitution
from pbpstats.resources.enhanced_pbp.rebound import EventOrderError
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_factory import (
    StatsNbaV3EnhancedPbpFactory,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.jump_ball import StatsNbaV3JumpBall
from pbpstats.resources.possessions.possession import Possession

from .decoder import (
    BLANK_FLAGRANT_FREE_THROW_VERSION,
    FOULS,
    FREE_THROWS,
    REBOUNDS,
    TEAMLESS_EXCESS_TIMEOUT_VERSION,
    TEAMLESS_TECHNICAL_VERSION,
    TECHNICAL_FREE_THROW_VERSION,
    TRANSITION_TAKE_FOUL_VERSION,
    VOIDED_SECOND_FREE_THROW_VERSION,
    TEAM_TURNOVERS,
    TURNOVERS,
    VIOLATIONS,
    DecodedV3,
    V3DecodeError,
    clock_text,
)
from .overrides import (
    BAD_POSSESSIONS,
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
from .starters import StarterRecovery
from .held_ball import HELD_BALL_VERSION, HeldBallJumpBall, is_candidate_at
from .team_heave import TEAM_HEAVE_VERSION, V3TeamHeave


TEAM_IDS_GUARD = "possession_team_ids_skip_teamless_events_v1"


class V3HeldBallJumpBall(HeldBallJumpBall, StatsNbaV3JumpBall):
    """A native jump ball under the held-ball rule."""


# NBA V3 records an and-one's basket, foul and free throw at one clock: from
# 2018-19 to 2025-26, 44,766 of the 44,772 baskets followed, past substitutions,
# timeouts and replays, by the other team's shooting or shooting block foul and
# the shooter's lone 1 of 1 at the foul's clock, or by its loose ball foul and a
# teammate's. The other six, as do 30 of 5,460 in 2017-18 and 5 of the first
# 142 in 2026-27, record the basket up to two seconds before the foul. The original
# decides an and-one from the events at the basket's clock alone, so a basket
# recorded early ends the possession before its free throw.
AND_ONE_CLOCK_VERSION = "nba_and_one_clock_v1"
AND_ONE_FOULS = {FOULS[label] for label in ("Shooting", "Shooting Block", "Loose Ball")}
# Rows a basket's foul can follow: substitutions, timeouts and replays.
DEAD_BALL_TYPES = (8, 9, 18)


def clock_seconds(text):
    """Seconds left in the period on an original "M:SS" clock."""
    minutes, _, rest = text.partition(":")
    return Decimal(minutes) * 60 + Decimal(rest)


# V3 subtype labels a reviewed correction may give each kind of event, with the
# V2 codes the decoder records for them (EVENTMSGTYPE: label -> action type).
# Free throws are the numbered regular ones only.
SUBTYPE_CODES = {
    3: {"Free Throw {} of {}".format(*key): code for key, code in FREE_THROWS.items()},
    4: dict(REBOUNDS),
    5: dict(TURNOVERS),
    6: dict(FOULS),
    7: dict(VIOLATIONS),
}


def reviewed_entries(overrides, name, game_id, empty):
    """One game's entries in a decoded reviewed-correction file."""
    games = overrides.get(name, {})
    return games.get(game_id, games.get(int(game_id), empty))


class V3Possession(Possession):
    """Original Possession with one defect guarded and reviewed clock resets.

    The original get_team_ids skips team-less events in its own possession but
    not in neighbouring ones. Replay events never have a team, in V2 or V3, so
    a lone jump-ball possession after a replay review raised AttributeError.
    Wherever the original returns, this returns the identical list.

    A possession that follows a reviewed game-clock reset starts at the clock
    the reset set, not at the previous possession's last clock.
    """

    @property
    def start_time(self):
        previous = getattr(self, "previous_possession", None)
        reset = getattr(previous.events[-1], "reviewed_clock_reset", None) if previous else None
        return reset if reset is not None else super().start_time

    def get_team_ids(self):
        def team_ids_of(possession):
            return [
                event.team_id
                for event in possession.events
                if hasattr(event, "team_id") and event.team_id != 0
            ]

        team_ids = list(set(team_ids_of(self)))
        prev_poss = self.previous_possession
        while len(team_ids) != 2 and prev_poss is not None:
            team_ids += team_ids_of(prev_poss)
            team_ids = list(set(team_ids))
            prev_poss = prev_poss.previous_possession
        next_poss = self.next_possession
        while len(team_ids) != 2 and next_poss is not None:
            team_ids += team_ids_of(next_poss)
            team_ids = list(set(team_ids))
            next_poss = next_poss.next_possession
        return team_ids


class _PreparedEvents(NbaEnhancedPbpLoader):
    """Events from the decoded rows: reviewed corrections, then the original's
    order repairs, linking and enhancement."""

    def __init__(
        self,
        decoded,
        validate_source_order,
        overrides=None,
        event_order=None,
        starter_boxscores=None,
    ):
        self.decoded = decoded
        self.overrides = overrides or {}
        self.recorded_event_order = event_order
        self.starter_boxscores = starter_boxscores or {}
        self.game_id = decoded.context.game_id
        self.file_directory = None
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
            self._make_pbp_items()
        else:
            self.factory = StatsNbaV3EnhancedPbpFactory()
            self.items = [
                self.factory.get_event_class(row["EVENTMSGTYPE"])(row, index)
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

    @property
    def league(self):
        # As the original's stats.nba.com loaders read it from the game ID.
        return {
            NBA_GAME_ID_PREFIX: NBA_STRING,
            G_LEAGUE_GAME_ID_PREFIX: G_LEAGUE_STRING,
            WNBA_GAME_ID_PREFIX: WNBA_STRING,
        }.get(self.game_id[:2])

    def _make_pbp_items(self):
        self._fix_order_when_technical_foul_before_period_start()
        self.factory = StatsNbaV3EnhancedPbpFactory()
        self.items = [
            self.factory.get_event_class(item["EVENTMSGTYPE"])(item, i)
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
                    self.factory.get_event_class(item["EVENTMSGTYPE"])(item, i)
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
                self.factory.get_event_class(item["EVENTMSGTYPE"])(item, i)
                for i, item in enumerate(self.data)
            ]
            self._add_extra_attrs_to_all_events()

    def _fix_order_when_technical_foul_before_period_start(self):
        # The original's: a technical foul recorded before its period's start
        # puts each period's start first, for periods 1 to 10.
        technical_foul_codes = [11, 12, 13, 16, 18, 19, 25, 30]
        starts_found, reorder = [], False
        for row in self.data:
            if row["EVENTMSGTYPE"] == 12:
                starts_found.append(row["PERIOD"])
            if (
                row["EVENTMSGTYPE"] == 6
                and row["EVENTMSGACTIONTYPE"] in technical_foul_codes
                and row["PERIOD"] not in starts_found
            ):
                reorder = True
        if not reorder:
            return
        starts, others = {}, {}
        for row in self.data:
            if row["EVENTMSGTYPE"] == 12:
                starts[row["PERIOD"]] = row
            else:
                others.setdefault(row["PERIOD"], []).append(row)
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
            if row["EVENTNUM"] == event_num:
                issue_event_index = i

        if rows[issue_event_index]["EVENTMSGTYPE"] in [8, 9]:
            # move all sub/timeout events between ft and rebound to before ft
            row_index = issue_event_index
            while rows[row_index]["EVENTMSGTYPE"] in [8, 9]:
                row_index -= 1
            new_rows = []
            row_to_move_event_num = rows[row_index]["EVENTNUM"]
            for row in rows:
                if row["EVENTNUM"] == row_to_move_event_num:
                    row_to_move = row
                elif row["EVENTNUM"] == event_num:
                    new_rows.append(row)
                    new_rows.append(row_to_move)
                else:
                    new_rows.append(row)
            self.data = new_rows
        elif (
            rows[issue_event_index]["EVENTMSGTYPE"] == 18
            and rows[issue_event_index + 1]["EVENTMSGTYPE"] == 4
        ):
            # move replay event after rebound
            rows[issue_event_index], rows[issue_event_index + 1] = (
                rows[issue_event_index + 1],
                rows[issue_event_index],
            )
        elif (
            rows[issue_event_index + 1]["EVENTMSGTYPE"] == 4
            and rows[issue_event_index + 1]["EVENTNUM"] == event_num - 1
        ):
            # rebound and shot need to be flipped
            rows[issue_event_index], rows[issue_event_index + 1] = (
                rows[issue_event_index + 1],
                rows[issue_event_index],
            )
        elif (
            rows[issue_event_index + 1]["EVENTMSGTYPE"] == 4
            and rows[issue_event_index + 1]["EVENTNUM"] == event_num + 2
            and rows[issue_event_index - 1]["EVENTMSGTYPE"] == 2
            and rows[issue_event_index - 1]["EVENTNUM"] == event_num + 1
        ):
            # shot, rebound, rebound - first rebound need to me moved to before shot
            rows[issue_event_index - 1], rows[issue_event_index] = (
                rows[issue_event_index],
                rows[issue_event_index - 1],
            )
        elif (
            rows[issue_event_index + 1]["EVENTMSGTYPE"] == 4
            and rows[issue_event_index + 1]["EVENTNUM"] == event_num - 2
            and rows[issue_event_index - 1]["EVENTMSGTYPE"] == 2
            and rows[issue_event_index - 1]["EVENTNUM"] == event_num - 1
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
        by_number = {row["EVENTNUM"]: row for row in self.data}

        def facts(row):
            return {key: value for key, value in row.items() if key != "EVENTNUM"}

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
        # removed event's actor the kept event's actor or second party.
        removals = self._reviewed_entries(EVENT_REMOVALS, {})
        duplicates = self._reviewed_entries(EVENT_DUPLICATES, {})
        by_number = {row["EVENTNUM"]: row for row in self.data}
        for event, kept in sorted(removals.items()):
            row, keeper = by_number.get(event), by_number.get(kept)
            if (
                row is None
                or keeper is None
                or kept in removals
                or kept in duplicates
                or (row["PERIOD"], row["EVENTMSGTYPE"])
                != (keeper["PERIOD"], keeper["EVENTMSGTYPE"])
                or not row["PLAYER1_ID"]
                or row["PLAYER1_ID"] not in (keeper["PLAYER1_ID"], keeper["PLAYER2_ID"])
            ):
                raise V3DecodeError("Event removal override does not fit the recorded events")
            self.data.remove(row)
            self.repairs.append(dict(code="reviewed_removed_event", event_num=event, kept=kept))

    def _apply_reviewed_blocks(self):
        # Records the blocker V3 omits as the decoder records a block row: as
        # PLAYER3 of a missed field goal, a player on the other team's roster.
        blocks = self._reviewed_entries(EVENT_BLOCKS, {})
        by_number = {row["EVENTNUM"]: row for row in self.data}
        roster = self.decoded.context.roster
        for event, player in sorted(blocks.items()):
            row = by_number.get(event)
            if (
                row is None
                or row["EVENTMSGTYPE"] != 2
                or row["PLAYER3_ID"] is not None
                or player not in roster
                or roster[player]["team_id"] == row["PLAYER1_TEAM_ID"]
            ):
                raise V3DecodeError("Event block override does not fit the recorded event")
            row["PLAYER3_ID"] = player
            self.repairs.append(dict(code="reviewed_event_block", event_num=event, blocker=player))

    def _apply_reviewed_tip_recipients(self):
        # Records who secured a jump ball, as PLAYER3 and its team, the fields the
        # original reads for the winning team. A team that secures it, as when the
        # tip goes out of bounds, is recorded as V2 and the decoder record a team
        # recovery: the team as PLAYER3, with no PLAYER3 team. The description
        # keeps V3's text.
        recipients = self._reviewed_entries(EVENT_TIP_RECIPIENTS, {})
        by_number = {row["EVENTNUM"]: row for row in self.data}
        roster = self.decoded.context.roster
        teams = self.decoded.context.team_ids
        for event, player in sorted(recipients.items()):
            row = by_number.get(event)
            if (
                row is None
                or row["EVENTMSGTYPE"] != 10
                or player not in roster and player not in teams
                or row["PLAYER3_ID"] == player
            ):
                raise V3DecodeError("Event tip-recipient override does not fit the recorded event")
            recorded = row["PLAYER3_ID"]
            row["PLAYER3_ID"] = player
            row["PLAYER3_TEAM_ID"] = None if player in teams else roster[player]["team_id"]
            self.repairs.append(dict(
                code="reviewed_tip_recipient", event_num=event, recorded=recorded, reviewed=player
            ))

    def _apply_reviewed_subtypes(self):
        # Edits the row's action type as the original's remedy of editing the
        # play-by-play file would. A free throw's label in its description
        # follows; other descriptions keep the recorded text.
        labels = self._reviewed_entries(EVENT_SUBTYPES, {})
        by_number = {row["EVENTNUM"]: row for row in self.data}
        for event, label in sorted(labels.items()):
            row = by_number.get(event)
            table = SUBTYPE_CODES.get(row["EVENTMSGTYPE"]) if row is not None else None
            names = {value: name for name, value in (table or {}).items()}
            if table is None or label not in table or row["EVENTMSGACTIONTYPE"] not in names:
                raise V3DecodeError("Event subtype override does not fit the recorded event")
            recorded = names[row["EVENTMSGACTIONTYPE"]]
            row["EVENTMSGACTIONTYPE"] = table[label]
            row["V3_SUB_TYPE"] = label
            if row["EVENTMSGTYPE"] == 3:
                row["NEUTRALDESCRIPTION"] = row["NEUTRALDESCRIPTION"].replace(recorded, label)
            self.repairs.append(dict(
                code="reviewed_event_subtype", event_num=event, recorded=recorded, reviewed=label
            ))

    def _apply_reviewed_clocks(self):
        # At most two seconds from the recorded clock, keeping the recorded order.
        clocks = self._reviewed_entries(EVENT_CLOCKS, {})
        rows = self.data
        index = {row["EVENTNUM"]: i for i, row in enumerate(rows)}
        for event, value in sorted(clocks.items()):
            if event not in index:
                raise V3DecodeError("Event clock override names an event not in the source")
            row, new = rows[index[event]], clock_text(value)
            if abs(clock_seconds(new) - clock_seconds(row["PCTIMESTRING"])) > 2:
                raise V3DecodeError("Event clock override moves an event more than two seconds")
            recorded, row["PCTIMESTRING"] = row["PCTIMESTRING"], new
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
                    and rows[before]["PERIOD"] == rows[after]["PERIOD"]
                    and clock_seconds(rows[before]["PCTIMESTRING"])
                    < clock_seconds(rows[after]["PCTIMESTRING"])
                ):
                    raise V3DecodeError("Event clock override breaks the recorded order")

    def _apply_reviewed_moves(self):
        # Moves an event V3 records at the wrong time to just after another
        # event of its period, taking that event's clock, as editing the
        # play-by-play file would.
        moves = self._reviewed_entries(EVENT_MOVES, {})
        rows = self.data
        for event, after in sorted(moves.items()):
            found = {row["EVENTNUM"]: row for row in rows}
            moved, anchor = found.get(event), found.get(after)
            if moved is None or anchor is None or moved["PERIOD"] != anchor["PERIOD"]:
                raise V3DecodeError("Event move override does not fit the recorded events")
            rows.remove(moved)
            recorded, moved["PCTIMESTRING"] = moved["PCTIMESTRING"], anchor["PCTIMESTRING"]
            rows.insert(rows.index(anchor) + 1, moved)
            self.repairs.append(dict(
                code="reviewed_moved_event", event_num=event, after=after,
                recorded=recorded, reviewed=moved["PCTIMESTRING"],
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
            if shot["EVENTMSGTYPE"] != 1:
                continue
            j = next(
                (
                    j
                    for j in range(i + 1, len(rows))
                    if rows[j]["EVENTMSGTYPE"] not in DEAD_BALL_TYPES
                ),
                None,
            )
            if j is None:
                continue
            foul = rows[j]
            period, clock, team = foul["PERIOD"], foul["PCTIMESTRING"], foul["PLAYER1_TEAM_ID"]
            if (
                foul["EVENTMSGTYPE"] != 6
                or foul["EVENTMSGACTIONTYPE"] not in AND_ONE_FOULS
                or period != shot["PERIOD"]
                or team in (None, shot["PLAYER1_TEAM_ID"])
                or not 0 < clock_seconds(shot["PCTIMESTRING"]) - clock_seconds(clock) <= 2
                or any(row["PCTIMESTRING"] != clock for row in rows[i + 1:j])
            ):
                continue
            at_foul = [r for r in rows if (r["PERIOD"], r["PCTIMESTRING"]) == (period, clock)]
            fouls = [
                r for r in at_foul if r["EVENTMSGTYPE"] == 6 and r["PLAYER1_TEAM_ID"] == team
            ]
            free_throws = [
                r
                for r in at_foul
                if r["EVENTMSGTYPE"] == 3 and r["PLAYER1_TEAM_ID"] == shot["PLAYER1_TEAM_ID"]
            ]
            if (
                len(fouls) != 1
                or len(free_throws) != 1
                or free_throws[0]["EVENTMSGACTIONTYPE"] != FREE_THROWS[1, 1]
                or foul["EVENTMSGACTIONTYPE"] != FOULS["Loose Ball"]
                and free_throws[0]["PLAYER1_ID"] != shot["PLAYER1_ID"]
            ):
                continue
            recorded, shot["PCTIMESTRING"] = shot["PCTIMESTRING"], clock
            self.repairs.append(dict(
                code=AND_ONE_CLOCK_VERSION, event_num=shot["EVENTNUM"],
                foul_event_num=foul["EVENTNUM"], free_throw_event_num=free_throws[0]["EVENTNUM"],
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
        index = {row["EVENTNUM"]: i for i, row in enumerate(rows)}
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
                or TURNOVERS[label] == 0
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
            row = dict.fromkeys(anchor)
            row.update(
                GAME_ID=anchor["GAME_ID"], EVENTNUM=event, PERIOD=anchor["PERIOD"],
                PCTIMESTRING=anchor["PCTIMESTRING"], PLAYER1_ID=person,
                PLAYER1_TEAM_ID=team, NEUTRALDESCRIPTION=description,
                EVENTMSGTYPE=5, EVENTMSGACTIONTYPE=TURNOVERS[label],
                V3_ACTION_TYPE="Turnover", V3_SUB_TYPE=label,
            )
            rows.insert(index[before], row)
            index = {r["EVENTNUM"]: i for i, r in enumerate(rows)}
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
            index = {row["EVENTNUM"]: i for i, row in enumerate(rows)}
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
                any(row["PERIOD"] != anchor["PERIOD"] for row in block)
                or clock_seconds(reset) <= clock_seconds(anchor["PCTIMESTRING"])
                or clock_seconds(block[0]["PCTIMESTRING"]) > clock_seconds(reset)
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
                    and before["PERIOD"] == after["PERIOD"]
                    and clock_seconds(before["PCTIMESTRING"])
                    < clock_seconds(after["PCTIMESTRING"])
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
            found = {row["EVENTNUM"]: row for row in rows}
            if event not in found or before not in found:
                raise V3DecodeError("Event-order override names an event not in the source")
            moved, anchor = found[event], found[before]
            if (moved["PERIOD"], moved["PCTIMESTRING"]) != (
                anchor["PERIOD"], anchor["PCTIMESTRING"]
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
        # Install extension events before linking/enhancement, without changing
        # the global factory or any original event's decision methods.
        rows = {r["EVENTNUM"]: r for r in self.data}
        self.items = [
            V3TeamHeave(rows[event.event_num], index)
            if event.event_num in self.decoded.team_heaves
            else V3HeldBallJumpBall(rows[event.event_num], index)
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
                "event_order": [row["EVENTNUM"] for row in self.data],
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
        by_number = {row["EVENTNUM"]: row for row in self.data}
        # Same ordering as the original provider fallback. Evidence validation
        # additionally prevents its silent dropping/duplication of source rows.
        self.data = [by_number[number] for number in order]
        self.repairs.append(deepcopy(diagnostic))
        self._save_data_to_file()


class StatsNbaV3PossessionLoader(StatsNbaPossessionLoader):
    """Experimental NBA adapter; accepts source bytes and hash-bound context.

    Native V3 event classes; the original's enhancement and possession decisions.
    ``validate_possessions=False`` is for differential event-sequence fixtures;
    it is not a declaration of full-game validity. Detailed V3 stats are gated.
    """

    def __init__(
        self,
        source_bytes,
        context,
        *,
        validate_possessions=True,
        validate_source_order=True,
        overrides=None,
        event_order=None,
        starter_boxscores=None,
        jump_balls=None,
    ):
        self.overrides, override_diagnostics = (
            overrides.decode(source_bytes) if overrides is not None else ({}, [])
        )
        decoded = DecodedV3(
            source_bytes,
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
        self.file_directory = None
        ordering = event_order.decode(decoded) if event_order is not None else None
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
            evidence.validate(source_bytes, context.game_id)
        enhanced = _PreparedEvents(
            decoded, validate_source_order, self.overrides, ordering, starter_boxscores
        )
        self.events = enhanced.items
        self.diagnostics = (
            override_diagnostics + enhanced.repairs
            + deepcopy(list(decoded.team_heaves.values()))
            + deepcopy(decoded.team_technicals)
            + deepcopy(decoded.label_rules)
            + deepcopy(decoded.inferred_codes)
            + deepcopy(decoded.non_roster_actors)
            + deepcopy(decoded.reviewed_inputs)
            + ([dict(decoded.live_input)] if decoded.live_input else [])
            + deepcopy(decoded.recorded_jump_balls)
        )
        self.items = [
            V3Possession(events) for events in self._split_events_by_possession()
        ]
        self._add_extra_attrs_to_all_possessions()
        held_balls = [
            event.diagnostic
            for event in self.events
            if isinstance(event, V3HeldBallJumpBall)
            and event.held_ball_turnover is not None
        ]
        self.diagnostics += held_balls
        if sum(len(possession.events) for possession in self.items) != len(self.events):
            raise V3DecodeError("Events left outside a possession")
        if any(
            getattr(event, "reviewed_clock_reset", None) is not None
            for possession in self.items
            for event in possession.events[:-1]
        ):
            raise V3DecodeError("A reviewed clock reset must end a possession")
        self._validate_lineups()
        if validate_possessions:
            self._load_bad_possession_overrides()
            self._check_that_possessions_alternate()
        self.capabilities = {
            "processing_rules": "original_v2_e7ccf2f",
            "full_game_validated": False,
            "detailed_event_stats": "unavailable",
            "source_order_checked": validate_source_order,
            "possession_sequence_checked": validate_possessions,
            "defect_guards": [TEAM_IDS_GUARD],
        }
        extensions = [TEAM_HEAVE_VERSION] if decoded.team_heaves else []
        rules = {
            rule.get("code")
            for rule in decoded.team_technicals + decoded.label_rules + enhanced.repairs
        }
        extensions += [
            version
            for version in (
                TEAMLESS_TECHNICAL_VERSION,
                TEAMLESS_EXCESS_TIMEOUT_VERSION,
                TECHNICAL_FREE_THROW_VERSION,
                TRANSITION_TAKE_FOUL_VERSION,
                BLANK_FLAGRANT_FREE_THROW_VERSION,
                VOIDED_SECOND_FREE_THROW_VERSION,
                AND_ONE_CLOCK_VERSION,
            )
            if version in rules
        ]
        if held_balls:
            extensions.append(HELD_BALL_VERSION)
        if extensions:
            self.capabilities["extensions"] = extensions

    def _load_bad_possession_overrides(self):
        self.bad_pbp_cases = deepcopy(self.overrides.get(BAD_POSSESSIONS, {}))

    def _validate_lineups(self):
        resolved = {r["event_num"]: r for r in self.decoded.participant_resolutions}
        # A reviewed outgoing player replaces the one V3 records already off
        # the floor, so the recorded player must be off it.
        recorded_outgoing = {
            d["event_num"]: d["recorded_player_id"]
            for d in self.decoded.reviewed_inputs
            if d["code"] == "reviewed_substitution_outgoing"
        }
        for event in self.events:
            if event.event_num in resolved:
                actual = sorted(
                    p for players in event.current_players.values() for p in players
                )
                if actual != resolved[event.event_num]["on_court"]:
                    raise V3DecodeError(
                        "Participant resolution disagrees with original enhanced lineup at event {}".format(
                            event.event_num
                        )
                    )
            if isinstance(event, Substitution):
                before = event.previous_event.current_players
                if (
                    event.player1_id not in before[event.team_id]
                    or event.player2_id in before[event.team_id]
                ):
                    raise V3DecodeError(
                        "Substitution contradicts current lineup at event {}".format(
                            event.event_num
                        )
                    )
                if (
                    event.event_num in recorded_outgoing
                    and recorded_outgoing[event.event_num] in before[event.team_id]
                ):
                    raise V3DecodeError(
                        "Event substitution-outgoing override does not fit the recorded event"
                    )
            for team, players in event.current_players.items():
                if len(players) != 5 or len(set(players)) != 5:
                    raise V3DecodeError(
                        "Invalid five-player lineup at event {}".format(event.event_num)
                    )
                if any(
                    player not in self.decoded.context.roster
                    or self.decoded.context.roster[player]["team_id"] != team
                    for player in players
                ):
                    raise V3DecodeError("Lineup contradicts roster")

    @property
    def counts_by_team(self):
        return dict(
            Counter(
                p.offense_team_id
                for p in self.items
                if p.events[-1].count_as_possession
            )
        )

    @property
    def base_stats(self):
        return [stat for event in self.events for stat in event.base_stats]

    @property
    def event_stats(self):
        raise V3DecodeError(
            "Detailed statistics are unavailable until attribution completeness is verified"
        )
