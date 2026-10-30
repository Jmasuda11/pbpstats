from pbpstats.resources.enhanced_pbp import Replay
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Replay(Replay, StatsNbaV3EnhancedPbpItem):
    """
    Class for replay events

    The original's rulings are V2's coach challenge codes 4, 5 and 6, so a replay
    without a coach challenge has none of them.
    """

    @property
    def support_ruling(self):
        return self.sub_type == "Coach Challenge Support Ruling"

    @property
    def overturn_ruling(self):
        return self.sub_type == "Coach Challenge Overturn Ruling"

    @property
    def ruling_stands(self):
        return self.sub_type == "Coach Challenge Ruling Stands"
