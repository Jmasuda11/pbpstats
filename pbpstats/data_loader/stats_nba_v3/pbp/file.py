from pbpstats.data_loader.abs_data_loader import check_file_directory
from pbpstats.data_loader.stats_nba_v3.file_loader import StatsNbaV3FileLoader


class StatsNbaV3PbpFileLoader(StatsNbaV3FileLoader):
    """
    A ``StatsNbaV3PbpFileLoader`` object should be instantiated and passed into ``StatsNbaV3PbpLoader`` when loading data from file

    :param str file_directory:
        Directory in which data should be loaded from.
        The specific file location will be `stats_v3_<game_id>.json` in the `/pbp` subdirectory.
    """

    def __init__(self, file_directory):
        self.file_directory = file_directory

    @check_file_directory
    def load_data(self, game_id):
        self.game_id = game_id
        self.file_path = f"{self.file_directory}/pbp/stats_v3_{self.game_id}.json"
        return self._load_data_from_file()
