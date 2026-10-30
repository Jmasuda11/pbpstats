from pbpstats.resources.enhanced_pbp import Turnover
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Turnover(Turnover, StatsNbaV3EnhancedPbpItem):
    """
    Class for Turnover events
    """

    def get_offense_team_id(self):
        """
        returns team id for team on offense for event
        """
        if self.is_no_turnover:
            return self.previous_event.get_offense_team_id()
        return self.team_id

    @property
    def is_no_turnover(self):
        # A turnover V3 records without a reason, which V2 codes 0.
        return self.sub_type == ""

    @property
    def is_bad_pass(self):
        return self.sub_type == "Bad Pass" and self.is_steal

    @property
    def is_lost_ball(self):
        return self.sub_type == "Lost Ball" and self.is_steal

    @property
    def is_travel(self):
        return self.sub_type == "Traveling"

    @property
    def is_3_second_violation(self):
        return self.sub_type == "3 Second Violation"

    @property
    def is_shot_clock_violation(self):
        return self.sub_type == "Shot Clock Turnover"

    @property
    def is_offensive_goaltending(self):
        return self.sub_type == "Offensive Goaltending"

    @property
    def is_lane_violation(self):
        return self.sub_type == "Lane Violation"

    @property
    def is_kicked_ball(self):
        return self.sub_type == "Kicked Ball Violation"

    @property
    def is_step_out_of_bounds(self):
        return self.sub_type == "Step Out of Bounds Turnover"

    @property
    def is_lost_ball_out_of_bounds(self):
        # some labelled as lost ball but should be lost ball out of bounds (missing player3 id)
        return self.sub_type == "Out of Bounds Lost Ball Turnover" or (
            self.sub_type == "Lost Ball" and not self.is_steal
        )

    @property
    def is_bad_pass_out_of_bounds(self):
        # some labelled as bad pass but should be bad pass out of bounds (missing player3 id)
        return self.sub_type == "Out of Bounds - Bad Pass Turnover" or (
            self.sub_type == "Bad Pass" and not self.is_steal
        )
