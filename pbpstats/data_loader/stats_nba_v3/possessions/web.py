from pbpstats.data_loader.stats_nba_v3.enhanced_pbp.web import (
    StatsNbaV3EnhancedPbpWebLoader,
)


class StatsNbaV3PossessionWebLoader(object):
    """
    A ``StatsNbaV3PossessionWebLoader`` object should be instantiated and passed into ``StatsNbaV3PossessionLoader`` when loading data directly from the NBA Stats API

    :param str file_directory: (optional, use it if you want to store the response data on disk)
        Directory in which data should be either stored, in the files
        :obj:`~pbpstats.data_loader.stats_nba_v3.enhanced_pbp.file.StatsNbaV3EnhancedPbpFileLoader` reads.
        If not provided response data will not be saved on disk.
    """

    def __init__(self, file_directory=None):
        self.file_directory = file_directory
        self.enhanced_pbp_source_loader = StatsNbaV3EnhancedPbpWebLoader(file_directory)
