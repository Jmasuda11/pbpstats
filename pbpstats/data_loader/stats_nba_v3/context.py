"""Explicit game and roster context; no implicit roster or network lookup."""

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Tuple

from pbpstats.data_loader.stats_nba_v3.pbp.loader import _validate_game_id


def _name_key(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def _positive_id(value):
    return type(value) is int and value > 0


@dataclass(frozen=True)
class V3RosterPlayer:
    player_id: int
    team_id: int
    aliases: Tuple[str, ...]

    def __post_init__(self):
        if not _positive_id(self.player_id) or not _positive_id(self.team_id):
            raise ValueError("roster player and team IDs must be positive integers")
        if isinstance(self.aliases, str):
            raise ValueError("aliases must be a sequence of names, not one string")
        aliases = tuple(self.aliases)
        if not aliases or any(
            not isinstance(n, str) or not _name_key(n) for n in aliases
        ):
            raise ValueError("each roster player needs nonempty name aliases")
        object.__setattr__(self, "aliases", aliases)


@dataclass(frozen=True)
class V3GameContext:
    game_id: str
    home_team_id: int
    away_team_id: int
    players: Tuple[V3RosterPlayer, ...] = ()
    roster_complete: bool = False
    roster_source: str = ""
    _players: object = field(init=False, repr=False, compare=False)
    _names: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        _validate_game_id(self.game_id)
        teams = self.team_ids
        if any(not _positive_id(t) for t in teams) or len(set(teams)) != 2:
            raise ValueError("game context requires two distinct positive team IDs")
        if type(self.roster_complete) is not bool:
            raise ValueError("roster_complete must be a boolean")
        if not isinstance(self.roster_source, str):
            raise ValueError("roster_source must be a string")
        if self.roster_complete and not self.roster_source.strip():
            raise ValueError("a complete roster requires its source provenance")
        players = tuple(self.players)
        by_id, names = {}, defaultdict(set)
        for player in players:
            if not isinstance(player, V3RosterPlayer):
                raise TypeError("players must contain V3RosterPlayer objects")
            if player.team_id not in teams or player.player_id in teams:
                raise ValueError(
                    "roster player/team identity conflicts with game context"
                )
            if player.player_id in by_id:
                raise ValueError(f"duplicate roster player {player.player_id}")
            by_id[player.player_id] = player
            for name in player.aliases:
                names[_name_key(name)].add(player.player_id)
        if self.roster_complete and {p.team_id for p in players} != set(teams):
            raise ValueError("a complete roster must cover both teams")
        object.__setattr__(self, "players", players)
        object.__setattr__(self, "_players", MappingProxyType(by_id))
        object.__setattr__(
            self,
            "_names",
            MappingProxyType({k: tuple(sorted(v)) for k, v in names.items()}),
        )

    @property
    def team_ids(self):
        return self.home_team_id, self.away_team_id

    def other_team(self, team_id):
        if team_id not in self.team_ids:
            raise ValueError("team is not part of this game context")
        return self.away_team_id if team_id == self.home_team_id else self.home_team_id

    def player(self, player_id):
        return self._players.get(player_id)

    def candidates(self, name, team_id=None):
        if team_id is not None and team_id not in self.team_ids:
            raise ValueError("team is not part of this game context")
        return tuple(
            pid
            for pid in self._names.get(_name_key(name), ())
            if team_id is None or self._players[pid].team_id == team_id
        )
