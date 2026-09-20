"""Validate a native V3 envelope and preserve one item per source action."""

import re
from copy import deepcopy

from pbpstats.resources.pbp.stats_nba_v3_pbp_item import StatsNbaV3PbpItem


def _validate_game_id(game_id):
    if not isinstance(game_id, str) or re.fullmatch(r"00[0-9]{8}", game_id) is None:
        raise ValueError(
            "Stats V3 game_id must be a 10-digit NBA string starting with 00"
        )


class StatsNbaV3PbpLoader:
    """Load raw V3 actions from a source exposing ``load_data(game_id)``.

    ``items`` contains every source row, including duplicates, blank action
    types, and unknown action types. ``data`` returns the original action list;
    ``source_data`` returns the whole JSON envelope. Both return defensive copies.
    ``source_bytes`` retains exact file bytes when supplied by the source loader.

    This raw loader accepts empty feeds and excerpts. It does not establish game
    completion, resolve participants, repair event order, or count possessions.
    Use these classes directly; registration with ``Client`` awaits web support.
    """

    data_provider = "stats_nba_v3"
    resource = "Pbp"
    parent_object = "Game"

    def __init__(self, game_id, source_loader):
        _validate_game_id(game_id)
        payload = source_loader.load_data(game_id)
        self._validate_envelope(payload, game_id)
        self.game_id = game_id
        self.file_directory = getattr(source_loader, "file_directory", None)
        self.source_bytes = getattr(source_loader, "source_bytes", None)
        self._source_data = deepcopy(payload)
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
        """Return the unmodified envelope, including unrecognized fields."""
        return deepcopy(self._source_data)

    @property
    def data(self):
        """Return source actions without adding derived metadata to their fields."""
        return deepcopy(self._source_data["game"]["actions"])
