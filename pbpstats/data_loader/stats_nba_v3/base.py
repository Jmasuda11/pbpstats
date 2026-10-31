from pbpstats import (
    G_LEAGUE_GAME_ID_PREFIX,
    G_LEAGUE_STRING,
    NBA_GAME_ID_PREFIX,
    NBA_STRING,
    WNBA_GAME_ID_PREFIX,
    WNBA_STRING,
)


class StatsNbaV3LoaderBase(object):
    """
    Base Class for all stats.nba.com play-by-play V3 data loaders

    This class should not be instantiated directly
    """

    @property
    def league(self):
        """
        Returns League for game id, as the original's stats.nba.com loaders read it.

        First 2 in game id represent league - 00 for nba, 10 for wnba, 20 for g-league
        """
        return {
            NBA_GAME_ID_PREFIX: NBA_STRING,
            G_LEAGUE_GAME_ID_PREFIX: G_LEAGUE_STRING,
            WNBA_GAME_ID_PREFIX: WNBA_STRING,
        }.get(self.game_id[:2])
