"""Validate a native V3 envelope and preserve one item per source action."""

import re
from typing import Any, NamedTuple, Optional

from pbpstats import NBA_GAME_ID_PREFIX
from pbpstats.resources.json_copy import json_copy
from pbpstats.resources.pbp.stats_nba_v3_pbp_item import StatsNbaV3PbpItem

GAME_ID_PATTERN = re.compile(rf"{NBA_GAME_ID_PREFIX}[0-9]{{8}}")


class V3PbpSourceData(NamedTuple):
    """What a V3 source loader returns from ``load_data``.

    The payload and the bytes it was decoded from travel together, so a
    source reused for several games cannot hand a loader another game's
    bytes, and a rejected payload cannot leave stale bytes behind.
    """

    payload: Any
    source_bytes: Optional[bytes] = None


def _validate_game_id(game_id):
    if not isinstance(game_id, str) or GAME_ID_PATTERN.fullmatch(game_id) is None:
        raise ValueError(
            "Stats V3 game_id must be a 10-digit NBA string starting with "
            f"{NBA_GAME_ID_PREFIX}"
        )


class StatsNbaV3PbpLoader:
    """Load raw V3 actions from a source exposing ``load_data(game_id)``.

    ``items`` contains every source row, including duplicates, blank action
    types, and unknown action types. ``data`` returns the original action list;
    ``source_data`` returns the whole JSON envelope. Both return defensive
    copies, built on each read, so bind them to a local rather than indexing
    them repeatedly. ``source_bytes`` retains the exact file bytes the source
    decoded the payload from.

    ``load_data`` must return a :class:`V3PbpSourceData`; any other return
    value is rejected rather than quietly leaving ``source_bytes`` unset.

    This raw loader accepts empty feeds and excerpts. It does not establish
    game completion, resolve participants, repair event order, or count
    possessions.

    :param str game_id: NBA Stats Game Id
    :param source_loader: :obj:`~pbpstats.data_loader.stats_nba_v3.pbp.file.StatsNbaV3PbpFileLoader` object
    """

    data_provider = "stats_nba_v3"
    resource = "Pbp"
    parent_object = "Game"

    def __init__(self, game_id, source_loader):
        _validate_game_id(game_id)
        source_data = source_loader.load_data(game_id)
        if not isinstance(source_data, V3PbpSourceData):
            raise TypeError(
                f"Stats V3 game {game_id}: "
                f"{type(source_loader).__name__}.load_data must return "
                f"V3PbpSourceData, got {type(source_data).__name__}"
            )
        self._validate_envelope(source_data.payload, game_id)
        self.game_id = game_id
        self.source_bytes = source_data.source_bytes
        try:
            self._source_data = json_copy(source_data.payload)
        except RecursionError as error:
            raise ValueError(
                f"Stats V3 game {game_id}: response nests too deeply to copy"
            ) from error
        self.items = [
            StatsNbaV3PbpItem(event, index, game_id)
            for index, event in enumerate(self._source_data["game"]["actions"])
        ]

    @staticmethod
    def _validate_envelope(payload, game_id):
        if not isinstance(payload, dict):
            raise ValueError(f"Stats V3 game {game_id}: response must be an object")
        game = payload.get("game")
        if not isinstance(game, dict):
            raise ValueError(f"Stats V3 game {game_id}: game must be an object")
        if game.get("gameId") != game_id:
            raise ValueError(
                f"Stats V3 game {game_id}: game.gameId is {game.get('gameId')!r}"
            )
        if not isinstance(game.get("actions"), list):
            raise ValueError(f"Stats V3 game {game_id}: game.actions must be an array")

    @property
    def source_data(self):
        """Return the unmodified envelope, including unrecognized fields.

        A fresh copy is built on every read; bind it to a local to reuse it.
        """
        return json_copy(self._source_data)

    @property
    def data(self):
        """Return source actions without adding derived metadata to their fields.

        A fresh copy is built on every read; bind it to a local to reuse it.
        """
        return json_copy(self._source_data["game"]["actions"])
