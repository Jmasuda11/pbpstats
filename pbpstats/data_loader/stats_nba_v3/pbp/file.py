"""Read recorded V3 JSON without network access or cache writes."""

import json
import math
from pathlib import Path

from pbpstats.data_loader.stats_nba_v3.pbp.loader import _validate_game_id


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number {value}")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"JSON number exceeds the supported float range: {value}")
    return number


class StatsNbaV3PbpFileLoader:
    """Read ``pbp/stats_v3_<game_id>.json`` under ``file_directory``.

    The original bytes are available as ``source_bytes`` after a successful
    read. JSON syntax errors raise ``ValueError`` with the game and file path;
    filesystem errors retain their native types, including ``FileNotFoundError``.
    Payload structure is validated by :class:`StatsNbaV3PbpLoader`.
    """

    def __init__(self, file_directory):
        if file_directory is None:
            raise ValueError("file_directory cannot be None when data source is file")
        self.file_directory = Path(file_directory)
        self.source_bytes = None

    def load_data(self, game_id):
        self.source_bytes = None
        _validate_game_id(game_id)
        file_path = self.file_directory / "pbp" / f"stats_v3_{game_id}.json"
        raw = file_path.read_bytes()
        try:
            payload = json.loads(
                raw.decode("utf-8-sig"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
        except (UnicodeError, ValueError) as error:
            raise ValueError(
                f"Stats V3 game {game_id}, file {file_path}: {error}"
            ) from error
        self.source_bytes = raw
        return payload
