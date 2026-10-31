"""
``StatsNbaV3EnhancedPbpItem`` is the base class for event types that decide from
stats.nba.com play-by-play V3 labels
"""
from collections import defaultdict

from pbpstats.resources.enhanced_pbp.stats_nba.enhanced_pbp_item import (
    StatsEnhancedPbpItem,
)


class StatsNbaV3EnhancedPbpItem(StatsEnhancedPbpItem):
    """
    Base class for enhanced pbp events from stats.nba.com play-by-play V3

    Decisions read the V3 action type and subtype. Everything that does not depend
    on how an event is recorded, such as the offense team, is the original's.

    :param dict event: the event's facts, as the decoder and the reviewed
        corrections name them
    :param int order: sequential order in which event occurs
    """

    def __init__(self, event, order):
        self.game_id = event["game_id"]
        self.event_num = event["event_num"]
        self.period = event["period"]
        self.clock = event["clock"]
        self.description = event["description"]
        self.action_type = event["action_type"]
        self.sub_type = event["sub_type"]
        self.player1_id = event["player1_id"]
        # The original decides from who is there: an event without a team, a
        # replay's, has no team_id, and one without a second or third person
        # has no player2_id or player3_id.
        if event["team_id"] is not None:
            self.team_id = event["team_id"]
        if event["player2_id"]:
            self.player2_id = event["player2_id"]
        if event["player3_id"]:
            self.player3_id = event["player3_id"]
        self.order = order
        self.player_game_fouls = defaultdict(int)
        self.possession_changing_override = False
        self.non_possession_changing_override = False
        self.score = defaultdict(int)

    def __repr__(self):
        # The original's exception messages print events by their stats_nba
        # class name, so StatsNbaV3Timeout prints as StatsTimeout.
        return super().__repr__().replace("<StatsNbaV3", "<Stats", 1)
