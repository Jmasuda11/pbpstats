from pbpstats.resources.enhanced_pbp import FreeThrow
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3FreeThrow(FreeThrow, StatsNbaV3EnhancedPbpItem):
    """
    Class for free throw events
    """

    @property
    def is_made(self):
        """
        returns True if shot was made, False otherwise
        """
        return "MISS " not in self.description

    def get_offense_team_id(self):
        """
        returns team id that took the shot
        """
        return self.team_id

    @property
    def is_ft_1_of_1(self):
        return self.sub_type in ["Free Throw 1 of 1", "Free Throw Flagrant 1 of 1"]

    @property
    def is_ft_1_of_2(self):
        return self.sub_type == "Free Throw 1 of 2"

    @property
    def is_ft_2_of_2(self):
        return self.sub_type == "Free Throw 2 of 2"

    @property
    def is_ft_1_of_3(self):
        return self.sub_type in ["Free Throw 1 of 3", "Free Throw Flagrant 1 of 3"]

    @property
    def is_ft_2_of_3(self):
        return self.sub_type == "Free Throw 2 of 3"

    @property
    def is_ft_3_of_3(self):
        return self.sub_type == "Free Throw 3 of 3"

    @property
    def is_technical_ft(self):
        return " Technical" in self.description

    @property
    def is_flagrant_ft(self):
        return " Flagrant" in self.description

    # The original's 1, 2 and 3 point free throws are G League codes, which no
    # NBA or WNBA V3 label records.

    @property
    def is_ft_1pt(self):
        return False

    @property
    def is_ft_2pt(self):
        return False

    @property
    def is_ft_3pt(self):
        return False
