from pbpstats.resources.enhanced_pbp import JumpBall
from pbpstats.resources.enhanced_pbp.possession_rules import JumpBallPossessionRules
from pbpstats.resources.enhanced_pbp.stats_nba.enhanced_pbp_item import (
    StatsEnhancedPbpItem,
)


class StatsJumpBall(JumpBall, JumpBallPossessionRules, StatsEnhancedPbpItem):
    """
    Class for jump ball events
    """

    event_type = 10

    def __init__(self, *args):
        super().__init__(*args)
