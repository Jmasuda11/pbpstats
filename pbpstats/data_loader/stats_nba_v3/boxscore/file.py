from pbpstats.data_loader.abs_data_loader import check_file_directory
from pbpstats.data_loader.stats_nba_v3.file_loader import StatsNbaV3FileLoader


class StatsNbaV3BoxscoreFileLoader(StatsNbaV3FileLoader):
    """
    A ``StatsNbaV3BoxscoreFileLoader`` object should be instantiated and passed into ``StatsNbaV3BoxscoreLoader`` when loading data from file

    :param str file_directory:
        Directory in which data should be loaded from.
        The specific file location will be `stats_v3_boxscore_<game_id>.json` in the `/game_details` subdirectory.
    """

    def __init__(self, file_directory):
        self.file_directory = file_directory

    @check_file_directory
    def load_data(self, game_id):
        self.game_id = game_id
        self.file_path = (
            f"{self.file_directory}/game_details/stats_v3_boxscore_{self.game_id}.json"
        )
        return self._load_data_from_file()
