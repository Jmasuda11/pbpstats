class StatsNbaV3PbpItem(object):
    """
    Class for pbp actions from stats.nba.com play-by-play V3

    :param dict item: dict with action data
    :param int order: sequential order in which action is recorded
    """

    def __init__(self, item, order):
        for key, value in item.items():
            setattr(self, key, value)
        self.order = order

    @property
    def data(self):
        """
        returns pbp action dict
        """
        return self.__dict__
