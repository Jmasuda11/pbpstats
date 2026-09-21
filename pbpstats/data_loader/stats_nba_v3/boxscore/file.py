"""Read a box score and its evidence sidecar without network or cache writes."""

from pathlib import Path

from pbpstats.data_loader.abs_data_loader import validate_file_directory
from pbpstats.data_loader.stats_nba_v3.boxscore.loader import V3BoxscoreSourceData
from pbpstats.data_loader.stats_nba_v3.pbp.loader import _validate_game_id


class StatsNbaV3BoxscoreFileLoader:
    """Read ``game_details/stats_v3_boxscore_<game_id>.json`` and
    ``game_details/stats_v3_boxscore_<game_id>.evidence.json``.

    Both files are required. Filesystem failures retain their native types.
    Each result binds both files' exact bytes and paths; the source is stateless.
    """

    def __init__(self, file_directory, *, league_id=None):
        validate_file_directory(file_directory)
        self.file_directory = Path(file_directory)
        self.league_id = league_id

    def load_data(self, game_id):
        _validate_game_id(game_id, self.league_id)
        path = self.file_directory / "game_details" / f"stats_v3_boxscore_{game_id}"
        boxscore = path.with_suffix(".json")
        evidence = path.with_suffix(".evidence.json")
        return V3BoxscoreSourceData(
            boxscore.read_bytes(), evidence.read_bytes(), str(boxscore), str(evidence)
        )
