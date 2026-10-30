"""
``StatsNbaV3EnhancedPbpFactory`` gives the class for each event type.
"""
from pbpstats.resources.enhanced_pbp.stats_nba_v3.ejection import StatsNbaV3Ejection
from pbpstats.resources.enhanced_pbp.stats_nba_v3.end_of_period import (
    StatsNbaV3EndOfPeriod,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.field_goal import StatsNbaV3FieldGoal
from pbpstats.resources.enhanced_pbp.stats_nba_v3.foul import StatsNbaV3Foul
from pbpstats.resources.enhanced_pbp.stats_nba_v3.free_throw import StatsNbaV3FreeThrow
from pbpstats.resources.enhanced_pbp.stats_nba_v3.jump_ball import StatsNbaV3JumpBall
from pbpstats.resources.enhanced_pbp.stats_nba_v3.rebound import StatsNbaV3Rebound
from pbpstats.resources.enhanced_pbp.stats_nba_v3.replay import StatsNbaV3Replay
from pbpstats.resources.enhanced_pbp.stats_nba_v3.start_of_period import (
    StatsNbaV3StartOfPeriod,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.substitution import (
    StatsNbaV3Substitution,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.timeout import StatsNbaV3Timeout
from pbpstats.resources.enhanced_pbp.stats_nba_v3.turnover import StatsNbaV3Turnover
from pbpstats.resources.enhanced_pbp.stats_nba_v3.violation import StatsNbaV3Violation

# Keyed by V2 event type, which the original's order repairs still read.
EVENT_CLASSES = {
    1: StatsNbaV3FieldGoal,
    2: StatsNbaV3FieldGoal,
    3: StatsNbaV3FreeThrow,
    4: StatsNbaV3Rebound,
    5: StatsNbaV3Turnover,
    6: StatsNbaV3Foul,
    7: StatsNbaV3Violation,
    8: StatsNbaV3Substitution,
    9: StatsNbaV3Timeout,
    10: StatsNbaV3JumpBall,
    11: StatsNbaV3Ejection,
    12: StatsNbaV3StartOfPeriod,
    13: StatsNbaV3EndOfPeriod,
    18: StatsNbaV3Replay,
}


class StatsNbaV3EnhancedPbpFactory:
    def get_event_class(self, event_type):
        return EVENT_CLASSES[event_type]
