"""Shared possession rules for validated enhanced event facts."""

from pbpstats.resources.enhanced_pbp import (
    FieldGoal,
    Foul,
    FreeThrow,
    JumpBall,
    Rebound,
    StartOfPeriod,
    Turnover,
    Violation,
)


class PossessionRules:
    def get_offense_team_id(self):
        """
        returns team id for team on offense for event
        """
        if isinstance(self, Foul) and (self.is_charge or self.is_offensive_foul):
            # offensive foul returns team id
            # this isn't separate method in Foul class because some fouls can be committed
            # on offense or defense (loose ball, flagrant, technical)
            return self.team_id
        event_to_check = self.previous_event
        team_ids = list(self.current_players.keys())
        while event_to_check is not None and not (
            isinstance(event_to_check, (FieldGoal, JumpBall))
            or (
                isinstance(event_to_check, Turnover)
                and not event_to_check.is_no_turnover
            )
            or (isinstance(event_to_check, Rebound) and event_to_check.is_real_rebound)
            or (
                isinstance(event_to_check, FreeThrow)
                and not event_to_check.is_technical_ft
            )
        ):
            event_to_check = event_to_check.previous_event
        if event_to_check is None and self.next_event is not None:
            # should only get here on first possession of period when first event is non-offensive foul,
            # FieldGoal, FreeThrow, Rebound, Turnover, JumpBall
            return self.next_event.get_offense_team_id()
        if isinstance(event_to_check, Turnover) and not event_to_check.is_no_turnover:
            return (
                team_ids[0]
                if team_ids[1] == event_to_check.get_offense_team_id()
                else team_ids[1]
            )
        if isinstance(event_to_check, Rebound) and event_to_check.is_real_rebound:
            if not event_to_check.oreb:
                return (
                    team_ids[0]
                    if team_ids[1] == event_to_check.get_offense_team_id()
                    else team_ids[1]
                )
            return event_to_check.get_offense_team_id()
        if isinstance(event_to_check, (FieldGoal, FreeThrow)):
            if event_to_check.is_possession_ending_event:
                return (
                    team_ids[0]
                    if team_ids[1] == event_to_check.get_offense_team_id()
                    else team_ids[1]
                )
            return event_to_check.get_offense_team_id()
        if isinstance(event_to_check, JumpBall):
            if event_to_check.count_as_possession:
                team_ids = list(self.current_players.keys())
                return (
                    team_ids[0]
                    if team_ids[1] == event_to_check.get_offense_team_id()
                    else team_ids[1]
                )
            return event_to_check.get_offense_team_id()

    @property
    def is_possession_ending_event(self):
        """
        returns True if event ends a possession, False otherwise
        """
        if self.next_event is None:
            return True

        if self.possession_changing_override:
            return True

        if self.non_possession_changing_override:
            return False

        if isinstance(self, Rebound) and self.is_real_rebound and not self.oreb:
            return True

        if isinstance(self, Turnover) and not self.is_no_turnover:
            return True

        if isinstance(self, FieldGoal) and self.is_made:
            # no possession change on flagrant foul
            next_event_is_flagrant_drawn = (
                isinstance(self.next_event, Foul)
                and self.next_event.is_flagrant
                and self.team_id != self.next_event.team_id
                and self.clock == self.next_event.clock
            )
            if (
                not self.is_make_that_does_not_end_possession
                and not next_event_is_flagrant_drawn
            ):
                return True

        if isinstance(self, FreeThrow) and self.is_made and self.is_end_ft:
            next_event_is_foul_drawn_at_ft_time = (
                isinstance(self.next_event, Foul)
                and self.clock == self.next_event.clock
                and self.team_id != self.next_event.team_id
                and (
                    self.next_event.is_loose_ball_foul
                    or self.next_event.is_personal_foul
                    or self.next_event.is_away_from_play_foul
                    or self.next_event.is_flagrant
                )
            )
            if (
                not self.is_away_from_play_ft
                and not self.is_inbound_foul_ft
                and not self.is_transition_take_foul_ft
                and not next_event_is_foul_drawn_at_ft_time
            ):
                return True

        if not isinstance(self.previous_event, StartOfPeriod) and isinstance(
            self, JumpBall
        ):
            return self._is_jump_ball_possession_ending_event()

        return False

    def _is_jump_ball_possession_ending_event(self):
        """
        need to check for rare case where possession changes on jump ball but there is no turnover/rebound
        """
        if (
            isinstance(self.next_event, Turnover)
            and not self.next_event.is_no_turnover
            and self.next_event.clock == self.clock
        ):
            # if next event is steal at same time of pbp don't need to change possession since steal takes care of it
            return False
        elif (
            isinstance(self.previous_event, Turnover)
            and not self.previous_event.is_no_turnover
            and self.previous_event.clock == self.clock
        ):
            # if previous event is steal at same time of pbp don't need to change possession since steal takes care of it
            return False
        elif (
            isinstance(self.next_event, Violation)
            and self.next_event.is_jumpball_violation
        ):
            # jump ball violation - turnover will be possession changing event
            return False
        elif isinstance(self.next_event, Foul) and self.next_event.clock == self.clock:
            next_event = self.next_event.next_event
            if (
                isinstance(next_event, Turnover)
                and not next_event.is_no_turnover
                and next_event.clock == self.clock
            ):
                # foul turnover on jump ball - turnover will trigger change of possession
                return False

        jump_ball_winning_team_id = self.team_id

        prev_event = self.previous_event
        while prev_event is not None and not prev_event.is_possession_ending_event:
            prev_event = prev_event.previous_event

        if prev_event is None:
            # Native adapters may have separately validated the period's initial
            # offense, including a held ball within the first possession.
            initial_offense = getattr(self, "initial_offense_team_id", None)
            if initial_offense is None:
                return False
            jump_ball_winning_team_started_possession_with_ball = (
                jump_ball_winning_team_id == initial_offense
            )
        elif isinstance(prev_event, Rebound):
            jump_ball_winning_team_started_possession_with_ball = (
                jump_ball_winning_team_id == prev_event.team_id
            )
        else:
            jump_ball_winning_team_started_possession_with_ball = (
                jump_ball_winning_team_id != prev_event.team_id
            )

        next_event_rebound = (
            isinstance(self.next_event, Rebound) and self.next_event.is_real_rebound
        )

        if not jump_ball_winning_team_started_possession_with_ball and not (
            next_event_rebound or isinstance(self.next_event, JumpBall)
        ):
            # ignore jump ball if next event is a rebound or jump ball since that will trigger possession change
            return True
        return False


class JumpBallPossessionRules:
    def get_offense_team_id(self):
        """
        returns team id for team on offense for event
        """
        if self.next_event.clock == self.clock and isinstance(
            self.next_event, Turnover
        ):
            return self.next_event.team_id
        if isinstance(self.next_event, Foul) and self.next_event.clock == self.clock:
            next_event = self.next_event.next_event
            if (
                isinstance(next_event, Turnover)
                and not next_event.is_no_turnover
                and next_event.clock == self.clock
            ):
                return next_event.team_id
        if self.count_as_possession:
            team_ids = list(self.current_players.keys())
            return team_ids[0] if team_ids[1] == self.team_id else team_ids[1]
        return self.team_id
