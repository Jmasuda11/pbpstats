"""Read recorded V3 JSON without network access or cache writes."""

import json
import math
from pathlib import Path

from pbpstats.data_loader.abs_data_loader import (
    check_file_directory,
    validate_file_directory,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import (
    V3PbpSourceData,
    _validate_game_id,
)


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

    ``load_data`` returns a :class:`~pbpstats.data_loader.stats_nba_v3.pbp.loader.V3PbpSourceData`
    carrying the payload and the exact bytes it was decoded from, so the two
    stay bound together and one loader can safely serve several games. This
    class keeps no per-game state.

    Malformed JSON raises ``ValueError`` naming the game and the file path;
    filesystem errors retain their native types, including ``FileNotFoundError``.
    Payload structure is validated by :class:`StatsNbaV3PbpLoader`.

    :param str file_directory: Directory in which data should be loaded from.
    """

    def __init__(self, file_directory, *, league_id=None):
        validate_file_directory(file_directory)
        self.file_directory = Path(file_directory)
        self.league_id = league_id

    @check_file_directory
    def load_data(self, game_id):
        _validate_game_id(game_id, self.league_id)
        file_path = self.file_directory / "pbp" / f"stats_v3_{game_id}.json"
        raw = file_path.read_bytes()
        try:
            payload = json.loads(
                raw.decode("utf-8-sig"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
        except (ValueError, RecursionError) as error:
            # UnicodeDecodeError and JSONDecodeError are both ValueError.
            # RecursionError is not, and deeply nested JSON raises it.
            raise ValueError(
                f"Stats V3 game {game_id}, file {file_path}: {error}"
            ) from error
        return V3PbpSourceData(payload=payload, source_bytes=raw)
