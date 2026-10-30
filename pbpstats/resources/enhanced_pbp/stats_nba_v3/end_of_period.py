from pbpstats.resources.enhanced_pbp import EndOfPeriod
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3EndOfPeriod(EndOfPeriod, StatsNbaV3EnhancedPbpItem):
    """
    Class for end of period events
    """
