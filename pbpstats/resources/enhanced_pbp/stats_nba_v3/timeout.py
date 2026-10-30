from pbpstats.resources.enhanced_pbp import Timeout
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Timeout(Timeout, StatsNbaV3EnhancedPbpItem):
    """
    Class for timeout events
    """
