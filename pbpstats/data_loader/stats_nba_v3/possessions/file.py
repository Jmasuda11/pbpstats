from pbpstats.data_loader.stats_nba_v3.enhanced_pbp.file import (
    StatsNbaV3EnhancedPbpFileLoader,
)


class StatsNbaV3PossessionFileLoader(object):
    """
    A ``StatsNbaV3PossessionFileLoader`` object should be instantiated and passed into ``StatsNbaV3PossessionLoader`` when loading data from file

    :param str file_directory:
        Directory in which data should be loaded from, in the files
        :obj:`~pbpstats.data_loader.stats_nba_v3.enhanced_pbp.file.StatsNbaV3EnhancedPbpFileLoader` reads.
    """

    def __init__(self, file_directory):
        self.file_directory = file_directory
        self.enhanced_pbp_source_loader = StatsNbaV3EnhancedPbpFileLoader(file_directory)
