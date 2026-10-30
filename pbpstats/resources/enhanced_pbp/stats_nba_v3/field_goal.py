from pbpstats.resources.enhanced_pbp import FieldGoal
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3FieldGoal(FieldGoal, StatsNbaV3EnhancedPbpItem):
    """
    Class for field goal events
    """

    @property
    def is_made(self):
        """
        returns True if shot was made, False otherwise
        """
        return self.action_type == "Made Shot"

    @property
    def shot_value(self):
        """
        returns 3 if shot is a 3 point attempt, 2 otherwise
        """
        # V3's description marks every three it records as one in shotValue.
        return 3 if " 3PT " in self.description else 2

    def get_offense_team_id(self):
        """
        returns team id that took the shot
        """
        return self.team_id
