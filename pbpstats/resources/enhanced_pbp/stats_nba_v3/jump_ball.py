from pbpstats.resources.enhanced_pbp import Foul, JumpBall, Turnover
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.held_ball import HeldBallJumpBall


class StatsNbaV3JumpBall(JumpBall, StatsNbaV3EnhancedPbpItem):
    """
    Class for jump ball events

    ``player2_id`` is the player the ball is tipped to and ``player3_id`` the
    other jumper. A ball tipped out of bounds has no ``player2_id``.
    """

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


class V3HeldBallJumpBall(HeldBallJumpBall, StatsNbaV3JumpBall):
    """
    Class for a jump ball under the held-ball rule
    """
