"""Versioned held-ball turnover: the original's same-clock rule at a later clock."""

from pbpstats.resources.enhanced_pbp import StartOfPeriod, Turnover
from pbpstats.resources.enhanced_pbp.stats_nba.jump_ball import StatsJumpBall


HELD_BALL_VERSION = "held_ball_turnover_v1"


def is_candidate(event, following):
    """Recorded structure only; the decision is made on the linked events."""
    return (
        isinstance(event, StatsJumpBall)
        and isinstance(following, Turnover)
        and following.period == event.period
        and not following.is_no_turnover
        and following.team_id != event.team_id
        and following.seconds_remaining < event.seconds_remaining
    )


class V3HeldBallJumpBall(StatsJumpBall):
    """A jump ball whose held-ball turnover is recorded after the tip.

    The original does not change possession at a jump ball when the next event
    is a turnover at the same clock ("steal takes care of it"). The league
    charges a held ball to the team that had the ball once its opponent
    secures the jump ball, sometimes at a later clock. When the original would
    change possession at this jump ball, because the team that won the tip did
    not have the ball, and the next event is a later turnover by the team that
    lost the tip, that turnover changes possession instead, exactly as at the
    same clock. Reviewed possession overrides still take precedence, and every
    other decision is the original's.
    """

    extension_version = HELD_BALL_VERSION

    @property
    def held_ball_turnover(self):
        """The turnover that changes possession instead of this jump ball, or None."""
        turnover = self.next_event
        if (
            is_candidate(self, turnover)
            and not isinstance(self.previous_event, StartOfPeriod)
            and not self.possession_changing_override
            and not self.non_possession_changing_override
            and super()._is_jump_ball_possession_ending_event()
        ):
            return turnover
        return None

    def _is_jump_ball_possession_ending_event(self):
        if self.held_ball_turnover is not None:
            return False
        return super()._is_jump_ball_possession_ending_event()

    def get_offense_team_id(self):
        turnover = self.held_ball_turnover
        if turnover is not None:
            return turnover.team_id
        return super().get_offense_team_id()

    @property
    def diagnostic(self):
        turnover = self.held_ball_turnover
        return dict(
            code=HELD_BALL_VERSION,
            event_num=self.event_num,
            turnover_event_num=turnover.event_num,
            period=self.period,
            jump_ball_clock=self.clock,
            turnover_clock=turnover.clock,
            tip_team_id=self.team_id,
            turnover_team_id=turnover.team_id,
            basis="original_same_clock_jump_ball_turnover_rule_at_recorded_turnover",
        )
