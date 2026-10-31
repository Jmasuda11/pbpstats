from pbpstats.resources.boxscore.live_boxscore_item import LiveBoxscoreItem


class StatsNbaV3BoxscoreItem(LiveBoxscoreItem):
    """
    Class for boxscore items from stats.nba.com boxscoretraditionalv3

    V3 records each player and team as the live data endpoint does: a person's
    ``personId``, ``firstName`` and ``familyName``, with stats under
    ``statistics``.

    :param dict item: dict with boxscore stats from response
    :param int team_id: team id is not in dict with stats and is added in here
    :param str team_abbreviation: team abbreviation is not in dict with stats and is added in here
    """
