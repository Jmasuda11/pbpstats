from pbpstats.data_loader.stats_nba_v3.web_loader import StatsNbaV3WebLoader, stats_url


class StatsNbaV3BoxscoreWebLoader(StatsNbaV3WebLoader):
    """
    A ``StatsNbaV3BoxscoreWebLoader`` object should be instantiated and passed into ``StatsNbaV3BoxscoreLoader`` when loading data directly from the NBA Stats API

    :param str file_directory: (optional, use it if you want to store the response data on disk)
        Directory in which data should be either stored.
        The specific file location will be `stats_v3_boxscore_<game_id>.json` in the `/game_details` subdirectory.
        If not provided response data will not be saved on disk.
    """

    def __init__(self, file_directory=None):
        self.file_directory = file_directory

    def load_data(self, game_id):
        self.game_id = game_id
        self.base_url = stats_url(game_id) + "boxscoretraditionalv3"
        self.parameters = {
            "GameID": game_id,
            "StartPeriod": 0,
            "EndPeriod": 0,
            "StartRange": 0,
            "EndRange": 0,
            "RangeType": 0,
        }
        self.file_path = (
            f"{self.file_directory}/game_details/stats_v3_boxscore_{self.game_id}.json"
        )
        return self._load_request_data()
