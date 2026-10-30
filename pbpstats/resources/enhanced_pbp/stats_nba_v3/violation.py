from pbpstats.resources.enhanced_pbp import Violation
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Violation(Violation, StatsNbaV3EnhancedPbpItem):
    """
    Class for violation events
    """

    @property
    def is_delay_of_game(self):
        return self.sub_type == "Delay Of Game"

    @property
    def is_goaltend_violation(self):
        return self.sub_type == "Defensive Goaltending"

    @property
    def is_lane_violation(self):
        return self.sub_type == "Lane"

    @property
    def is_jumpball_violation(self):
        return self.sub_type == "Jump Ball"

    @property
    def is_kicked_ball_violation(self):
        return self.sub_type == "Kicked Ball"

    @property
    def is_double_lane_violation(self):
        return self.sub_type == "Double Lane"
