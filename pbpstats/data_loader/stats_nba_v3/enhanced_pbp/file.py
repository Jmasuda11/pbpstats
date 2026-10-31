from pathlib import Path

from pbpstats.data_loader.stats_nba_v3.boxscore.file import StatsNbaV3BoxscoreFileLoader
from pbpstats.data_loader.stats_nba_v3.decoder import V3JumpBallEvidenceRequired
from pbpstats.data_loader.stats_nba_v3.file_loader import SavedResponse
from pbpstats.data_loader.stats_nba_v3.overrides import (
    reviewed_aliases,
    reviewed_overrides,
)
from pbpstats.data_loader.stats_nba_v3.pbp.file import StatsNbaV3PbpFileLoader
from pbpstats.data_loader.stats_nba_v3.starters import V3EvidenceRequired


class StatsNbaV3EnhancedPbpFileLoader(StatsNbaV3PbpFileLoader):
    """
    A ``StatsNbaV3EnhancedPbpFileLoader`` object should be instantiated and passed into ``StatsNbaV3EnhancedPbpLoader`` when loading data from file

    Recorded evidence is read only when the parse asks for it; a request that
    is not recorded is an error naming it.

    :param str file_directory:
        Directory in which data should be loaded from.
        The play-by-play is `stats_v3_<game_id>.json`, and any live play-by-play
        `live_<game_id>.json`, in the `/pbp` subdirectory. The box score is
        `stats_v3_boxscore_<game_id>.json`, and any period-start box score the original requests
        `stats_boxscoretraditionalv2_<game_id>_period_<period>.json`, in the `/game_details` subdirectory.
        Reviewed aliases, if any, are `player_aliases.json` in the `/overrides` subdirectory.
    """

    def __init__(self, file_directory):
        self.file_directory = file_directory
        self.boxscore_source_loader = StatsNbaV3BoxscoreFileLoader(file_directory)

    def load_overrides(self, game_id, pbp_bytes):
        return reviewed_overrides(game_id, pbp_bytes)

    def load_aliases(self, boxscore):
        return reviewed_aliases(self.file_directory, boxscore)

    def load_starter_boxscore(self, period, url, params):
        path = Path(
            f"{self.file_directory}/game_details/stats_boxscoretraditionalv2_{self.game_id}_period_{period}.json"
        )
        if not path.is_file():
            raise V3EvidenceRequired(
                f"{path} does not exist", period=period, url=url, params=params
            )
        return SavedResponse(path.read_bytes(), url)

    def load_live(self, url):
        path = Path(f"{self.file_directory}/pbp/live_{self.game_id}.json")
        if not path.is_file():
            raise V3JumpBallEvidenceRequired(f"{path} does not exist", url=url)
        return SavedResponse(path.read_bytes(), url)
