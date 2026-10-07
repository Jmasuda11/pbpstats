"""Versioned held-ball turnover: the original's same-clock rule at the recorded turnover."""

from pbpstats.resources.enhanced_pbp import StartOfPeriod, Substitution, Turnover
from pbpstats.resources.enhanced_pbp.stats_nba.jump_ball import StatsJumpBall


HELD_BALL_VERSION = "held_ball_turnover_v2"


def is_stoppage_substitution(jump_ball, event):
    """A substitution logged at the jump ball's clock, made while play was stopped."""
    return (
        isinstance(event, Substitution)
        and event.period == jump_ball.period
        and event.clock == jump_ball.clock
    )


def is_candidate(event, following, substitutions=()):
    """Recorded structure only; the decision is made on the linked events.

    A turnover right after the jump ball at its clock is the original's own
    same-clock case. Past stoppage substitutions, the same clock qualifies.
    """
    return (
        isinstance(event, StatsJumpBall)
        and isinstance(following, Turnover)
        and following.period == event.period
        and not following.is_no_turnover
        and following.team_id != event.team_id
        and (
            following.seconds_remaining < event.seconds_remaining
            or bool(substitutions)
            and following.seconds_remaining == event.seconds_remaining
        )
    )


def is_candidate_at(items, index):
    """``is_candidate`` for an unlinked event list, past stoppage substitutions."""
    event = items[index]
    if not isinstance(event, StatsJumpBall):
        return False
    following = index + 1
    while following < len(items) and is_stoppage_substitution(event, items[following]):
        following += 1
    return is_candidate(
        event,
        items[following] if following < len(items) else None,
        items[index + 1:following],
    )


class V3HeldBallJumpBall(StatsJumpBall):
    """A jump ball whose held-ball turnover is recorded after the tip.

    The original does not change possession at a jump ball when the next event
    is a turnover at the same clock ("steal takes care of it"). The league
    charges a held ball to the team that had the ball once its opponent
    secures the jump ball, sometimes at a later clock, and substitutions made
    while play was stopped can be logged between the jump ball and that
    turnover. When the original would change possession at this jump ball,
    because the team that won the tip did not have the ball, and the first
    event past those substitutions is a turnover by the team that lost the
    tip, that turnover changes possession instead, exactly as the original's
    same-clock rule does for a turnover that immediately follows.

    A held ball can also tie up a player who has just made a steal. The
    original already keeps the possession through that jump ball, because
    the steal's turnover at the same clock changed it ("steal takes care of
    it"). When the team that lost the ball on the steal wins the tip and the
    stealer's team is charged after it, that turnover decides the jump ball's
    offense, as the same-clock rule would. Reviewed possession overrides still
    take precedence, and every other decision is the original's.
    """

    extension_version = HELD_BALL_VERSION

    @property
    def stoppage_substitutions(self):
        """Substitutions logged at this clock between the jump ball and its turnover."""
        substitutions, event = [], self.next_event
        while is_stoppage_substitution(self, event):
            substitutions.append(event)
            event = event.next_event
        return substitutions

    @property
    def steal_turnover(self):
        """The same-clock turnover just before the tip by the team that won it, or None."""
        previous = self.previous_event
        if (
            isinstance(previous, Turnover)
            and not previous.is_no_turnover
            and previous.clock == self.clock
            and previous.team_id == self.team_id
        ):
            return previous
        return None

    @property
    def held_ball_turnover(self):
        """The turnover that changes possession instead of this jump ball, or None."""
        substitutions = self.stoppage_substitutions
        turnover = substitutions[-1].next_event if substitutions else self.next_event
        if (
            is_candidate(self, turnover, substitutions)
            and not isinstance(self.previous_event, StartOfPeriod)
            and not self.possession_changing_override
            and not self.non_possession_changing_override
            and (
                self.steal_turnover is not None
                or super()._is_jump_ball_possession_ending_event()
            )
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
            substitution_event_nums=[x.event_num for x in self.stoppage_substitutions],
            steal_turnover_event_num=(
                self.steal_turnover.event_num if self.steal_turnover is not None else None
            ),
            period=self.period,
            jump_ball_clock=self.clock,
            turnover_clock=turnover.clock,
            tip_team_id=self.team_id,
            turnover_team_id=turnover.team_id,
            basis="original_same_clock_jump_ball_turnover_rule_at_recorded_turnover",
        )
