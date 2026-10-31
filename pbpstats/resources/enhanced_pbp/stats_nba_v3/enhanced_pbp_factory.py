"""
``StatsNbaV3EnhancedPbpFactory`` gives the class for each decoded event.
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
from pbpstats.resources.enhanced_pbp.stats_nba_v3.team_heave import V3TeamHeave
from pbpstats.resources.enhanced_pbp.stats_nba_v3.substitution import (
    StatsNbaV3Substitution,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.timeout import StatsNbaV3Timeout
from pbpstats.resources.enhanced_pbp.stats_nba_v3.turnover import StatsNbaV3Turnover
from pbpstats.resources.enhanced_pbp.stats_nba_v3.violation import StatsNbaV3Violation

EVENT_CLASSES = {
    "Made Shot": StatsNbaV3FieldGoal,
    "Missed Shot": StatsNbaV3FieldGoal,
    # The decoder rejects a heave that is not a recorded team heave.
    "Heave": V3TeamHeave,
    "Free Throw": StatsNbaV3FreeThrow,
    "Rebound": StatsNbaV3Rebound,
    "Turnover": StatsNbaV3Turnover,
    "Foul": StatsNbaV3Foul,
    "Violation": StatsNbaV3Violation,
    "Substitution": StatsNbaV3Substitution,
    "Timeout": StatsNbaV3Timeout,
    "Jump Ball": StatsNbaV3JumpBall,
    "Ejection": StatsNbaV3Ejection,
    "Instant Replay": StatsNbaV3Replay,
}
# V3 records a period's start and its end as one action type, "period".
PERIOD_CLASSES = {"start": StatsNbaV3StartOfPeriod, "end": StatsNbaV3EndOfPeriod}


class StatsNbaV3EnhancedPbpFactory:
    def get_event_class(self, event):
        """
        returns the class for a decoded event, by its V3 action type, and a
        period's by its subtype
        """
        if event["action_type"] == "period":
            return PERIOD_CLASSES[event["sub_type"]]
        return EVENT_CLASSES[event["action_type"]]
