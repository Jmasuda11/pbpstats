"""Offline construction of ORIGINAL enhanced classes and possession objects."""

from collections import Counter
from copy import deepcopy
from decimal import Decimal
import math

from pbpstats.data_loader.stats_nba.enhanced_pbp.loader import StatsNbaEnhancedPbpLoader
from pbpstats.data_loader.stats_nba.possessions.loader import StatsNbaPossessionLoader
from pbpstats.resources.enhanced_pbp import FieldGoal, Substitution
from pbpstats.resources.enhanced_pbp.stats_nba.enhanced_pbp_factory import (
    StatsNbaEnhancedPbpFactory,
)
from pbpstats.resources.possessions.possession import Possession

from .decoder import (
    FOULS,
    FREE_THROWS,
    REBOUNDS,
    TURNOVERS,
    VIOLATIONS,
    DecodedV3,
    V3DecodeError,
    clock_text,
)
from .overrides import (
    BAD_POSSESSIONS,
    CHANGE_EVENTS,
    EVENT_CLOCKS,
    EVENT_ORDER,
    EVENT_SUBTYPES,
    KEEP_EVENTS,
    STARTERS,
)
from .starters import StarterRecovery
from .held_ball import HELD_BALL_VERSION, V3HeldBallJumpBall, is_candidate_at
from .team_heave import TEAM_HEAVE_VERSION, V3TeamHeave


TEAM_IDS_GUARD = "possession_team_ids_skip_teamless_events_v1"


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

class V3Possession(Possession):
    """Original Possession with one defect guarded.

    The original get_team_ids skips team-less events in its own possession but
    not in neighbouring ones. Replay events never have a team, in V2 or V3, so
    a lone jump-ball possession after a replay review raised AttributeError.
    Wherever the original returns, this returns the identical list.
    """

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


class _PreparedEvents(StatsNbaEnhancedPbpLoader):
    """Supply recorded context and redirect original loader I/O into memory."""

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
        headers = list(decoded.projected[0])
        # Existing source-order repairs consume this internal projection. It is
        # separate from decoded.payload, raw_rows and immutable source_bytes.
        self.source_data = {
            "resultSets": [
                {
                    "headers": headers,
                    "rowSet": [
                        [row.get(key) for key in headers] for row in decoded.projected
                    ],
                }
            ]
        }
        self._apply_reviewed_subtypes()
        self._apply_reviewed_clocks()
        self._apply_reviewed_event_order()
        if validate_source_order:
            self._make_pbp_items()
        else:
            self.factory = StatsNbaEnhancedPbpFactory()
            self.items = [
                self.factory.get_event_class(row["EVENTMSGTYPE"])(row, index)
                for index, row in enumerate(self.data)
            ]
            self._add_extra_attrs_to_all_events()
            self._add_shot_x_y_coords()
        for event in self.items:
            group = decoded.groups[event.event_num]
            event.v3_source_indices = group["source_indices"]
            event.v3_source_row = deepcopy(group["primary"])

    def _reviewed_entries(self, name, empty):
        games = self.overrides.get(name, {})
        return games.get(self.game_id, games.get(int(self.game_id), empty))

    def _apply_reviewed_subtypes(self):
        # Edits the projection's action type as the original's remedy of editing
        # the play-by-play file would. A free throw's label in its description
        # follows; other descriptions keep the recorded text.
        labels = self._reviewed_entries(EVENT_SUBTYPES, {})
        result = self.source_data["resultSets"][0]
        headers = result["headers"]
        kind, code = headers.index("EVENTMSGTYPE"), headers.index("EVENTMSGACTIONTYPE")
        by_number = {row[headers.index("EVENTNUM")]: row for row in result["rowSet"]}
        for event, label in sorted(labels.items()):
            row = by_number.get(event)
            table = SUBTYPE_CODES.get(row[kind]) if row is not None else None
            names = {value: name for name, value in (table or {}).items()}
            if table is None or label not in table or row[code] not in names:
                raise V3DecodeError("Event subtype override does not fit the recorded event")
            recorded = names[row[code]]
            row[code] = table[label]
            if row[kind] == 3:
                for key in ("HOMEDESCRIPTION", "VISITORDESCRIPTION", "NEUTRALDESCRIPTION"):
                    if key in headers and isinstance(row[headers.index(key)], str):
                        row[headers.index(key)] = row[headers.index(key)].replace(recorded, label)
            self.repairs.append(dict(
                code="reviewed_event_subtype", event_num=event, recorded=recorded, reviewed=label
            ))

    def _apply_reviewed_clocks(self):
        # Tenths only, within the recorded second, keeping the recorded order.
        clocks = self._reviewed_entries(EVENT_CLOCKS, {})
        result = self.source_data["resultSets"][0]
        headers = result["headers"]
        number, period, clock = (
            headers.index(key) for key in ("EVENTNUM", "PERIOD", "PCTIMESTRING")
        )
        rows = result["rowSet"]
        index = {row[number]: i for i, row in enumerate(rows)}

        def seconds(text):
            minutes, _, rest = text.partition(":")
            return Decimal(minutes) * 60 + Decimal(rest)

        for event, value in sorted(clocks.items()):
            if event not in index:
                raise V3DecodeError("Event clock override names an event not in the source")
            row, new = rows[index[event]], clock_text(value)
            if int(seconds(new)) != int(seconds(row[clock])):
                raise V3DecodeError("Event clock override moves an event to another second")
            recorded, row[clock] = row[clock], new
            self.repairs.append(dict(
                code="reviewed_event_clock", event_num=event, recorded=recorded, reviewed=new
            ))
        # Only the edited events' neighbours are checked: a recording can hold
        # inversions elsewhere that the original's own order repairs fix.
        for event in clocks:
            i = index[event]
            for before, after in ((i - 1, i), (i, i + 1)):
                if 0 <= before and after < len(rows) and rows[before][period] == rows[after][period]                         and seconds(rows[before][clock]) < seconds(rows[after][clock]):
                    raise V3DecodeError("Event clock override breaks the recorded order")

    def _apply_reviewed_event_order(self):
        # The original's remedy for events recorded out of order is to edit the
        # play-by-play file. Reviewed moves edit this projection the same way,
        # once, before the original loads it.
        moves = self._reviewed_entries(EVENT_ORDER, [])
        if not moves:
            return
        result = self.source_data["resultSets"][0]
        number, period, clock = (
            result["headers"].index(key) for key in ("EVENTNUM", "PERIOD", "PCTIMESTRING")
        )
        rows = result["rowSet"]
        for event, before in moves:
            found = {row[number]: row for row in rows}
            if event not in found or before not in found:
                raise V3DecodeError("Event-order override names an event not in the source")
            moved, anchor = found[event], found[before]
            if (moved[period], moved[clock]) != (anchor[period], anchor[clock]):
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
        order, diagnostic = self.recorded_event_order
        result = self.source_data["resultSets"][0]
        number_index = result["headers"].index("EVENTNUM")
        by_number = {row[number_index]: row for row in result["rowSet"]}
        # Same ordering as the original provider fallback. Evidence validation
        # additionally prevents its silent dropping/duplication of source rows.
        result["rowSet"] = [by_number[number] for number in order]
        self.repairs.append(deepcopy(diagnostic))
        self._save_data_to_file()


class StatsNbaV3PossessionLoader(StatsNbaPossessionLoader):
    """Experimental NBA adapter; accepts source bytes and hash-bound context.

    The original event classes, enhancement and possession decisions are reused.
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
        decoded = DecodedV3(source_bytes, context, jump_balls)
        self.decoded = decoded
        self.game_id = context.game_id
        self.file_directory = None
        self.overrides, override_diagnostics = (
            overrides.decode(source_bytes) if overrides is not None else ({}, [])
        )
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
            + deepcopy(decoded.non_roster_actors)
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
        if held_balls:
            extensions.append(HELD_BALL_VERSION)
        if extensions:
            self.capabilities["extensions"] = extensions

    def _load_bad_possession_overrides(self):
        self.bad_pbp_cases = deepcopy(self.overrides.get(BAD_POSSESSIONS, {}))

    def _validate_lineups(self):
        resolved = {r["event_num"]: r for r in self.decoded.participant_resolutions}
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
