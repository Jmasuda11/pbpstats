"""
``StatsNbaV3EnhancedPbpItem`` is the base class for event types that decide from
stats.nba.com play-by-play V3 labels
"""
from pbpstats.resources.enhanced_pbp.stats_nba.enhanced_pbp_item import (
    StatsEnhancedPbpItem,
)


class StatsNbaV3EnhancedPbpItem(StatsEnhancedPbpItem):
    """
    Base class for enhanced pbp events from stats.nba.com play-by-play V3

    Decisions read the V3 action type and subtype. Everything that does not depend
    on how an event is recorded, such as the offense team, is the original's.

    :param dict event: dict with event data
    :param int order: sequential order in which event occurs
    """

    def __init__(self, event, order):
        super().__init__(event, order)
        self.action_type = event["V3_ACTION_TYPE"]
        self.sub_type = event["V3_SUB_TYPE"]
        # Never decide from V2's action type code.
        self.__dict__.pop("event_action_type", None)

    def __repr__(self):
        # The original's exception messages print events by their stats_nba
        # class name, so StatsNbaV3Timeout prints as StatsTimeout.
        return super().__repr__().replace("<StatsNbaV3", "<Stats", 1)
