"""Native V3 facts implementing the shared possession engine's event protocol.

Detailed event statistics intentionally fail until their full evidence contract
is implemented; ``base_stats`` supplies the shared time/possession statistics.
"""

from collections import defaultdict
from decimal import Context, localcontext
from math import isfinite

from pbpstats.resources.enhanced_pbp import (
    EndOfPeriod,
    FieldGoal,
    Foul,
    FreeThrow,
    JumpBall,
    Rebound,
    Replay,
    StartOfPeriod,
    Substitution,
    Timeout,
    Turnover,
    Violation,
)
from pbpstats.resources.enhanced_pbp.enhanced_pbp_item import EnhancedPbpItem
from pbpstats.resources.enhanced_pbp.possession_rules import (
    JumpBallPossessionRules,
    PossessionRules,
)
from pbpstats.resources.period_clock import CLOCK_PATTERN


class V3EnhancedEvent(PossessionRules, EnhancedPbpItem):
    def __init__(self, lineup, order):
        self.lineup = lineup
        self.facts = lineup.event
        row = self.facts.group.primary
        self.game_id, self.period, self.event_num = (
            row.game_id,
            row.period,
            row.action_number,
        )
        self.order, self.description = order, row.description
        # Canonical exact display ensures equivalent ISO clocks compare equally.
        minutes, seconds = CLOCK_PATTERN.fullmatch(row.get("clock")).groups()
        whole, _, fraction = seconds.partition(".")
        fraction = fraction.rstrip("0")
        suffix = "." + fraction if fraction else ""
        self.clock = f"{int(minutes)}:{str(int(whole)).zfill(2)}{suffix}"
        self.team_id = self.facts.team_id or 0
        self.player1_id = self.facts.participants.participants["actor"].player_id or 0
        self.score = defaultdict(int)
        self.player_game_fouls = defaultdict(int)
        self.possession_changing_override = False
        self.non_possession_changing_override = False

    def error(self, message):
        return ValueError(
            f"Stats V3 game {self.game_id}, source rows "
            f"{self.facts.group.source_indices}: {message}"
        )

    @property
    def seconds_remaining(self):
        return self.facts.group.primary.seconds_remaining_exact

    @property
    def seconds_since_previous_event(self):
        if self.previous_event is None:
            return 0
        precision = max(28, len(self.clock) + len(self.previous_event.clock) + 5)
        with localcontext(Context(prec=precision)):
            return self.previous_event.seconds_remaining - self.seconds_remaining

    @property
    def current_players(self):
        return self.lineup.after

    @property
    def data(self):
        return self.facts.group.primary.data

    @property
    def event_stats(self):
        raise self.error(
            "detailed V3 event statistics are unavailable; use base_stats for "
            "validated possession/time statistics; foul-drawn identities are not inferred"
        )


class V3FieldGoal(V3EnhancedEvent, FieldGoal):
    _and_one = None
    _retained_make = False

    def __init__(self, lineup, order):
        super().__init__(lineup, order)
        for source, attr in (("xLegacy", "locX"), ("yLegacy", "locY")):
            value = self.facts.group.primary.get(source)
            if value is not None:
                if type(value) not in (int, float) or not isfinite(value):
                    raise self.error(f"{source} requires finite numeric coordinates")
                setattr(self, attr, value)

    @property
    def is_corner_3(self):
        if self.shot_value == 3 and not hasattr(self, "locY"):
            raise self.error("three-point shot location is unavailable")
        return FieldGoal.is_corner_3.fget(self)

    def _has_participant(self, role):
        participant = self.facts.participants.participants.get(role)
        if participant is None or participant.status == "absent":
            return False
        self.facts.participants.require_player(role)
        return True

    @property
    def is_blocked(self):
        return not self.is_made and self._has_participant("blocker")

    @property
    def is_assisted(self):
        return self.is_made and self._has_participant("assister")

    @property
    def is_made(self):
        return self.facts.is_made

    @property
    def shot_value(self):
        return self.facts.shot_value

    @property
    def is_make_that_does_not_end_possession(self):
        return self._and_one is not None or self._retained_make

    @property
    def is_and1(self):
        return self._and_one is not None

    def get_offense_team_id(self):
        return self.team_id


class V3FreeThrow(V3EnhancedEvent, FreeThrow):
    is_ft_1pt = is_ft_2pt = is_ft_3pt = False
    is_away_from_play_ft = is_inbound_foul_ft = is_transition_take_foul_ft = False

    @property
    def is_made(self):
        return self.facts.is_made

    @property
    def is_technical_ft(self):
        return self.facts.free_throw.category == "technical"

    @property
    def is_flagrant_ft(self):
        return self.facts.free_throw.category == "flagrant"

    @property
    def is_end_ft(self):
        return (
            self.facts.free_throw.category == "regular"
            and self.facts.free_throw.is_last_attempt
        )

    @property
    def is_first_ft(self):
        return self.facts.free_throw.attempt == 1

    @property
    def is_ft_1_of_1(self):
        return self._trip_position == (1, 1)

    @property
    def is_ft_1_of_2(self):
        return self._trip_position == (1, 2)

    @property
    def is_ft_2_of_2(self):
        return self._trip_position == (2, 2)

    @property
    def is_ft_1_of_3(self):
        return self._trip_position == (1, 3)

    @property
    def is_ft_2_of_3(self):
        return self._trip_position == (2, 3)

    @property
    def is_ft_3_of_3(self):
        return self._trip_position == (3, 3)

    @property
    def _trip_position(self):
        ft = self.facts.free_throw
        return (ft.attempt, ft.total) if ft.category == "regular" else None

    @property
    def foul_that_led_to_ft(self):
        return self.trip_foul

    @property
    def event_for_efficiency_stats(self):
        return self.trip_foul

    def get_offense_team_id(self):
        if self.is_technical_ft:
            return PossessionRules.get_offense_team_id(self)
        return self.team_id


class V3Foul(V3EnhancedEvent, Foul):
    is_inbound_foul = is_away_from_play_foul = is_double_foul = False
    is_double_technical = is_defensive_3_seconds = is_delay_of_game = False
    is_personal_block_foul = is_personal_take_foul = False
    is_shooting_block_foul = is_transition_take_foul = False
    number_of_fta_for_foul = None

    @property
    def is_personal_foul(self):
        return self.facts.subtype == "Personal"

    @property
    def is_shooting_foul(self):
        return self.facts.subtype == "Shooting"

    @property
    def is_loose_ball_foul(self):
        return self.facts.subtype == "Loose Ball"

    @property
    def is_offensive_foul(self):
        return self.facts.subtype == "Offensive"

    @property
    def is_charge(self):
        return self.facts.subtype == "Offensive Charge"

    @property
    def is_technical(self):
        return self.facts.subtype == "Technical"

    @property
    def is_clear_path_foul(self):
        return self.facts.subtype == "Clear Path"

    @property
    def is_flagrant1(self):
        return self.facts.subtype == "Flagrant Type 1"

    @property
    def is_flagrant2(self):
        return self.facts.subtype == "Flagrant Type 2"


class V3Rebound(V3EnhancedEvent, Rebound):
    def is_penalty_event(self):
        if self.is_placeholder:
            return self.previous_event.is_penalty_event()
        return super().is_penalty_event()

    @property
    def missed_shot(self):
        return self._missed_shot

    @property
    def is_placeholder(self):
        return self.placeholder_reason is not None

    @property
    def is_real_rebound(self):
        return not self.is_placeholder

    @property
    def oreb(self):
        if self.is_placeholder:
            raise self.error(
                "placeholder rebound has no offensive/defensive classification"
            )
        return self.team_id == self.missed_shot.team_id

    def get_offense_team_id(self):
        if self.is_real_rebound:
            return self.missed_shot.team_id
        return PossessionRules.get_offense_team_id(self)


class V3Turnover(V3EnhancedEvent, Turnover):
    is_no_turnover = (
        is_kicked_ball
    ) = is_offensive_goaltending = is_lane_violation = False

    @property
    def is_steal(self):
        participant = self.facts.participants.participants["stealer"]
        if participant.status == "absent":
            return False
        self.facts.participants.require_player("stealer")
        return True

    @property
    def is_shot_clock_violation(self):
        return self.facts.subtype == "Shot Clock Turnover"

    @property
    def is_bad_pass(self):
        return self.facts.subtype == "Bad Pass" and self.is_steal

    @property
    def is_lost_ball(self):
        return self.facts.subtype == "Lost Ball" and self.is_steal

    @property
    def is_travel(self):
        return self.facts.subtype == "Traveling"

    @property
    def is_3_second_violation(self):
        return self.facts.subtype == "3 Second Violation"

    @property
    def is_step_out_of_bounds(self):
        return self.facts.subtype == "Step Out of Bounds Turnover"

    @property
    def is_lost_ball_out_of_bounds(self):
        return self.facts.subtype == "Out of Bounds Lost Ball Turnover" or (
            self.facts.subtype == "Lost Ball" and not self.is_steal
        )

    @property
    def is_bad_pass_out_of_bounds(self):
        return self.facts.subtype == "Out of Bounds - Bad Pass Turnover" or (
            self.facts.subtype == "Bad Pass" and not self.is_steal
        )

    def get_offense_team_id(self):
        return self.team_id


class V3Violation(V3EnhancedEvent, Violation):
    is_jumpball_violation = is_double_lane_violation = False

    @property
    def is_lane_violation(self):
        return self.facts.subtype == "Lane"

    @property
    def is_goaltend_violation(self):
        return self.facts.subtype == "Defensive Goaltending"

    @property
    def is_kicked_ball_violation(self):
        return self.facts.subtype == "Kicked Ball"

    @property
    def is_delay_of_game(self):
        return self.facts.subtype == "Delay Of Game"


class V3StartOfPeriod(V3EnhancedEvent, StartOfPeriod):
    def get_period_starters(self, file_directory=None):
        return self.lineup.before

    def get_offense_team_id(self):
        return self.team_starting_with_ball


class V3JumpBall(V3EnhancedEvent, JumpBall):
    def get_offense_team_id(self):
        return JumpBallPossessionRules.get_offense_team_id(self)


class V3Substitution(V3EnhancedEvent, Substitution):
    @property
    def outgoing_player_id(self):
        return self.player1_id

    @property
    def incoming_player_id(self):
        return self.player2_id


class V3Timeout(V3EnhancedEvent, Timeout):
    pass


class V3Replay(V3EnhancedEvent, Replay):
    pass


class V3EndOfPeriod(V3EnhancedEvent, EndOfPeriod):
    pass


EVENT_CLASSES = {
    "field_goal": V3FieldGoal,
    "free_throw": V3FreeThrow,
    "foul": V3Foul,
    "rebound": V3Rebound,
    "turnover": V3Turnover,
    "violation": V3Violation,
    "period_start": V3StartOfPeriod,
    "period_end": V3EndOfPeriod,
    "jump_ball": V3JumpBall,
    "substitution": V3Substitution,
    "timeout": V3Timeout,
    "replay": V3Replay,
}
