from pbpstats.resources.enhanced_pbp import Substitution
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Substitution(Substitution, StatsNbaV3EnhancedPbpItem):
    """
    Class for substitution events
    """

    @property
    def outgoing_player_id(self):
        """
        returns player id of player going out of the game
        """
        return self.player1_id

    @property
    def incoming_player_id(self):
        """
        returns player id of player coming in to the game
        """
        return self.player2_id
