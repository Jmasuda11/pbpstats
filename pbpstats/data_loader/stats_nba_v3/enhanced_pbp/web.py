import requests

from pbpstats import REQUEST_TIMEOUT
from pbpstats.data_loader.stats_nba_v3.boxscore.web import StatsNbaV3BoxscoreWebLoader
from pbpstats.data_loader.stats_nba_v3.overrides import (
    reviewed_aliases,
    reviewed_overrides,
)
from pbpstats.data_loader.stats_nba_v3.pbp.web import StatsNbaV3PbpWebLoader
from pbpstats.data_loader.stats_nba_v3.web_loader import get, save_response


class StatsNbaV3EnhancedPbpWebLoader(StatsNbaV3PbpWebLoader):
    """
    A ``StatsNbaV3EnhancedPbpWebLoader`` object should be instantiated and passed into ``StatsNbaV3EnhancedPbpLoader`` when loading data directly from the NBA Stats API

    Evidence is requested only when the parse asks for it: the original's
    period-start box score request, and the league's live play-by-play for a
    jump ball V3 leaves undecided.

    :param str file_directory: (optional, use it if you want to store the response data on disk)
        Directory in which data should be either stored, in the files
        :obj:`~pbpstats.data_loader.stats_nba_v3.enhanced_pbp.file.StatsNbaV3EnhancedPbpFileLoader` reads.
        Only a successful period-start box score response is stored.
        If not provided response data will not be saved on disk.
    """

    def __init__(self, file_directory=None):
        self.file_directory = file_directory
        self.boxscore_source_loader = StatsNbaV3BoxscoreWebLoader(file_directory)

    def load_overrides(self, game_id, pbp_bytes):
        return reviewed_overrides(game_id, pbp_bytes)

    def load_aliases(self, boxscore):
        return reviewed_aliases(self.file_directory, boxscore)

    def load_starter_boxscore(self, period, url, params):
        response = get(url, params)
        if response.status_code == 200:
            save_response(
                self.file_directory,
                f"{self.file_directory}/game_details/stats_boxscoretraditionalv2_{self.game_id}_period_{period}.json",
                response.content,
            )
        return response

    def load_live(self, url):
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        save_response(
            self.file_directory,
            f"{self.file_directory}/pbp/live_{self.game_id}.json",
            response.content,
        )
        return response
