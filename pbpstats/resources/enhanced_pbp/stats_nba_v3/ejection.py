from pbpstats.resources.enhanced_pbp import Ejection
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Ejection(Ejection, StatsNbaV3EnhancedPbpItem):
    """
    Class for ejection events
    """
