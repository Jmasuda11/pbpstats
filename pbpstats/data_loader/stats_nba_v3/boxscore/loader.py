"""
``StatsNbaV3BoxscoreLoader`` loads boxscoretraditionalv3 data for a game and creates :obj:`~pbpstats.resources.boxscore.stats_nba_v3_boxscore_item.StatsNbaV3BoxscoreItem` objects for each player and team

The following code will load boxscore data for game id "0022500001" from a file located in a subdirectory of the /data directory

.. code-block:: python

    from pbpstats.data_loader import StatsNbaV3BoxscoreFileLoader, StatsNbaV3BoxscoreLoader

    source_loader = StatsNbaV3BoxscoreFileLoader("/data")
    boxscore_loader = StatsNbaV3BoxscoreLoader("0022500001", source_loader)
    print(boxscore_loader.items[0].data) # prints dict with a player's boxscore data for game
"""
import json

from pbpstats.data_loader.stats_nba_v3.base import StatsNbaV3LoaderBase
from pbpstats.resources.boxscore.stats_nba_v3_boxscore_item import (
    StatsNbaV3BoxscoreItem,
)


class StatsNbaV3BoxscoreLoader(StatsNbaV3LoaderBase):
    """
    Loads stats.nba.com source boxscoretraditionalv3 data for game.
    Team/Player data is stored in items attribute as :obj:`~pbpstats.resources.boxscore.stats_nba_v3_boxscore_item.StatsNbaV3BoxscoreItem` objects:
    the home team's players, the away team's players, then the home and away teams.

    :param str game_id: NBA Stats Game Id
    :param source_loader: :obj:`~pbpstats.data_loader.stats_nba_v3.boxscore.file.StatsNbaV3BoxscoreFileLoader` or :obj:`~pbpstats.data_loader.stats_nba_v3.boxscore.web.StatsNbaV3BoxscoreWebLoader` object
    """

    data_provider = "stats_nba_v3"
    resource = "Boxscore"
    parent_object = "Game"

    def __init__(self, game_id, source_loader):
        self.game_id = game_id
        self.source_data = source_loader.load_data(self.game_id)
        self._make_boxscore_items()

    def _make_boxscore_items(self):
        """
        makes :obj:`~pbpstats.resources.boxscore.stats_nba_v3_boxscore_item.StatsNbaV3BoxscoreItem` items for each player/team
        """
        box = self.data
        # A side's players belong to the team the box score names for that side.
        sides = [
            (box["homeTeamId"], box["homeTeam"]),
            (box["awayTeamId"], box["awayTeam"]),
        ]
        self.items = [
            StatsNbaV3BoxscoreItem(
                player, team_id=team_id, team_abbreviation=team.get("teamTricode")
            )
            for team_id, team in sides
            for player in team["players"]
        ]
        self.items += [
            StatsNbaV3BoxscoreItem(
                team.get("statistics", {}),
                team_id=team_id,
                team_abbreviation=team.get("teamTricode"),
            )
            for team_id, team in sides
        ]

    @property
    def home_team_id(self):
        return self.data["homeTeamId"]

    @property
    def away_team_id(self):
        return self.data["awayTeamId"]

    @property
    def data(self):
        """
        returns the box score from the raw JSON response
        """
        return json.loads(self.source_data)["boxScoreTraditional"]
