"""
``StatsNbaV3PbpLoader`` loads play-by-play V3 data for a game and
creates :obj:`~pbpstats.resources.pbp.stats_nba_v3_pbp_item.StatsNbaV3PbpItem` objects for each recorded action

The following code will load pbp data for game id "0022500001" from a file
located in a subdirectory of the /data directory

.. code-block:: python

    from pbpstats.data_loader import StatsNbaV3PbpFileLoader, StatsNbaV3PbpLoader

    source_loader = StatsNbaV3PbpFileLoader("/data")
    pbp_loader = StatsNbaV3PbpLoader("0022500001", source_loader)
    print(pbp_loader.items[0].data)  # prints dict with the first action of the game
"""
import json

from pbpstats.data_loader.stats_nba_v3.base import StatsNbaV3LoaderBase
from pbpstats.resources.pbp.stats_nba_v3_pbp_item import StatsNbaV3PbpItem


class StatsNbaV3PbpLoader(StatsNbaV3LoaderBase):
    """
    Loads stats.nba.com source play-by-play V3 data for game.
    Actions are stored in items attribute
    as :obj:`~pbpstats.resources.pbp.stats_nba_v3_pbp_item.StatsNbaV3PbpItem` objects

    :param str game_id: NBA Stats Game Id
    :param source_loader: :obj:`~pbpstats.data_loader.stats_nba_v3.pbp.file.StatsNbaV3PbpFileLoader` or :obj:`~pbpstats.data_loader.stats_nba_v3.pbp.web.StatsNbaV3PbpWebLoader` object
    """

    data_provider = "stats_nba_v3"
    resource = "Pbp"
    parent_object = "Game"

    def __init__(self, game_id, source_loader):
        self.game_id = game_id
        self.source_data = source_loader.load_data(self.game_id)
        self.file_directory = source_loader.file_directory
        self._make_pbp_items()

    def _make_pbp_items(self):
        self.items = [StatsNbaV3PbpItem(item, i) for i, item in enumerate(self.data)]

    @property
    def data(self):
        """
        returns the recorded actions from the raw JSON response
        """
        return json.loads(self.source_data)["game"]["actions"]
