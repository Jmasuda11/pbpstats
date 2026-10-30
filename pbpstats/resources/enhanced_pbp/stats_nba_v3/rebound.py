from pbpstats.resources.enhanced_pbp import (
    FieldGoal,
    FreeThrow,
    JumpBall,
    Rebound,
    Substitution,
    Timeout,
    Turnover,
)
from pbpstats.resources.enhanced_pbp.rebound import EventOrderError
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Rebound(Rebound, StatsNbaV3EnhancedPbpItem):
    """
    Class for rebound events
    """

    def get_offense_team_id(self):
        """
        returns team id for team on offense for the shot that was rebounded
        """
        if self.is_real_rebound:
            return self.missed_shot.team_id
        if (
            isinstance(self.previous_event, Turnover)
            and not self.previous_event.is_no_turnover
        ):
            # shot clock turnover has place holder rebound after turnover
            # this correct team starts next possession
            team_ids = list(self.current_players.keys())
            return (
                team_ids[0]
                if team_ids[1] == self.previous_event.team_id
                else team_ids[1]
            )
        return self.previous_event.get_offense_team_id()

    @property
    def missed_shot(self):
        """
        returns :obj:`~pbpstats.resources.enhanced_pbp.field_goal.FieldGoal` or
        :obj:`~pbpstats.resources.enhanced_pbp.free_throw.FreeThrow` object
        for shot that was missed

        :raises: :obj:`~pbpstats.resources.enhanced_pbp.rebound.EventOrderError`:
            If rebound event is not immediately following a missed shot event.
        """
        if isinstance(self.previous_event, (FieldGoal, FreeThrow)):
            if not self.previous_event.is_made:
                return self.previous_event
        elif (
            isinstance(self.previous_event, Turnover)
            and self.previous_event.is_shot_clock_violation
        ):
            if isinstance(self.previous_event, FieldGoal):
                return self.previous_event.previous_event
        elif isinstance(self.previous_event, JumpBall):
            prev_event = self.previous_event.previous_event
            while isinstance(prev_event, (Substitution, Timeout)):
                prev_event = prev_event.previous_event
            if isinstance(prev_event, (FieldGoal, FreeThrow)):
                return prev_event
        raise EventOrderError(
            f"previous event: {self.previous_event} is not a missed free throw or field goal"
        )

    @property
    def is_placeholder(self):
        """
        returns True if rebound is a placeholder event, False otherwise.

        These are team rebounds on for example missed FT 1 of 2. V3 labels
        them "Normal Rebound", V2's code 1, and every other rebound "Unknown".
        """
        return self.sub_type == "Normal Rebound" and self.player1_id == 0

    @property
    def oreb(self):
        """
        returns True if rebound is an offensive rebound, False otherwise
        """
        return self.team_id == self.missed_shot.team_id
