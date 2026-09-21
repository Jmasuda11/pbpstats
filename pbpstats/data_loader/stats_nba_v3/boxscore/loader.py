"""Validate native box-score identity evidence, independently of period starters."""

import hashlib
import json
from typing import NamedTuple

from pbpstats.data_loader.stats_nba_v3.context import (
    V3BenchPerson,
    V3GameContext,
    V3RosterPlayer,
    _name_key,
    _positive_id,
)
from pbpstats.data_loader.stats_nba_v3.pbp.file import (
    _finite_float,
    _reject_constant,
    _unique_object,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import _validate_game_id
from pbpstats.resources.json_copy import json_copy


class V3BoxscoreSourceData(NamedTuple):
    """Exact input bytes and source locations, decoded together by the loader."""

    boxscore_bytes: bytes
    evidence_bytes: bytes
    boxscore_source: str
    evidence_source: str


class StatsNbaV3BoxscoreLoader:
    """Build ``context`` from a traditional V3 box score and evidence sidecar.

    The sidecar binds provenance and an explicit roster-completeness declaration
    to the response's SHA-256. Complete means the declared game player pool, with
    the documented alias policy; it never establishes on-court players or period
    starters. Partial/unknown coverage is usable for explicit identities but
    cannot certify unique description-only names in the participant resolver.

    This is a context loader, not a statistical ``Client`` Boxscore resource.
    Raw statistics and starter-looking fields are preserved but not interpreted.
    """

    def __init__(self, game_id, source_loader, *, league_id=None):
        self.league_id = _validate_game_id(game_id, league_id)
        self.game_id = game_id
        source = source_loader.load_data(game_id)
        if not isinstance(source, V3BoxscoreSourceData):
            raise TypeError(
                f"Stats V3 game {game_id}: load_data must return V3BoxscoreSourceData"
            )
        self.source = source
        for field in ("boxscore_source", "evidence_source"):
            self._text(getattr(source, field), field)
        self._source_data = self._decode(source.boxscore_bytes, source.boxscore_source)
        self._evidence = self._decode(source.evidence_bytes, source.evidence_source)
        self.source_sha256 = hashlib.sha256(source.boxscore_bytes).hexdigest()
        self.evidence_sha256 = hashlib.sha256(source.evidence_bytes).hexdigest()
        self._validate_evidence()
        self.context = self._build_context()

    def _error(self, message):
        return ValueError(
            f"Stats V3 game {self.game_id}, boxscore {self.source.boxscore_source}, "
            f"evidence {self.source.evidence_source}: {message}"
        )

    def _decode(self, raw, location):
        if not isinstance(raw, bytes):
            raise self._error(f"{location}: source must supply bytes")
        try:
            result = json.loads(
                raw.decode("utf-8-sig"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
            # Check the same recursive copy used by the public accessors now,
            # so accepted unknown fields cannot fail later during inspection.
            result = json_copy(result)
        except (ValueError, RecursionError) as error:
            raise self._error(f"{location}: {error}") from error
        if not isinstance(result, dict):
            raise self._error(f"{location}: response must be an object")
        return result

    def _text(self, value, field):
        if not isinstance(value, str) or not _name_key(value):
            raise self._error(f"{field} must be a nonempty string")
        return value

    def _id(self, value, field):
        if not _positive_id(value):
            raise self._error(f"{field} must be a positive integer")
        return value

    def _validate_evidence(self):
        evidence = self._evidence
        if (
            type(evidence.get("schema_version")) is not int
            or evidence["schema_version"] != 1
        ):
            raise self._error("evidence.schema_version must be 1")
        if evidence.get("game_id") != self.game_id:
            raise self._error("evidence.game_id does not match requested game")
        if evidence.get("boxscore_sha256") != self.source_sha256:
            raise self._error("evidence.boxscore_sha256 does not match response bytes")
        self._text(evidence.get("source"), "evidence.source")
        if evidence.get("scope") not in ("full_game", "partial", "unknown"):
            raise self._error("evidence.scope must be full_game, partial, or unknown")
        complete = evidence.get("roster_complete")
        if type(complete) is not bool:
            raise self._error("evidence.roster_complete must be a boolean")
        if complete:
            if evidence["scope"] != "full_game":
                raise self._error("complete roster requires full_game scope")
            self._text(
                evidence.get("completeness_basis"), "evidence.completeness_basis"
            )
        if not isinstance(evidence.get("aliases", []), list):
            raise self._error("evidence.aliases must be an array")

    def _build_context(self):
        box = self._source_data.get("boxScoreTraditional")
        if not isinstance(box, dict):
            raise self._error("boxScoreTraditional must be an object")
        if box.get("gameId") != self.game_id:
            raise self._error(
                "boxScoreTraditional.gameId does not match requested game"
            )
        teams = tuple(
            self._id(box.get(f"{side}TeamId"), f"{side}TeamId")
            for side in ("home", "away")
        )
        if teams[0] == teams[1]:
            raise self._error("home and away team IDs must be distinct")
        players, aliases, names = {}, {}, {}
        for side, team_id in zip(("home", "away"), teams):
            label = f"boxScoreTraditional.{side}Team"
            team = box.get(f"{side}Team")
            if not isinstance(team, dict):
                raise self._error(f"{label} must be an object")
            if self._id(team.get("teamId"), f"{label}.teamId") != team_id:
                raise self._error(f"{label}.teamId conflicts with {side}TeamId")
            rows = team.get("players")
            if not isinstance(rows, list):
                raise self._error(f"{label}.players must be an array")
            if self._evidence["roster_complete"] and len(rows) < 5:
                raise self._error(
                    f"{label}: complete roster needs at least five players"
                )
            for index, row in enumerate(rows):
                location = f"{label}.players[{index}]"
                if not isinstance(row, dict):
                    raise self._error(f"{location} must be an object")
                pid = self._id(row.get("personId"), f"{location}.personId")
                if pid in teams or pid in players:
                    raise self._error(
                        f"{location}: duplicate or conflicting player ID {pid}"
                    )
                if (
                    "teamId" in row
                    and self._id(row["teamId"], f"{location}.teamId") != team_id
                ):
                    raise self._error(
                        f"{location}.teamId conflicts with containing team"
                    )
                first = self._text(row.get("firstName"), f"{location}.firstName")
                family = self._text(row.get("familyName"), f"{location}.familyName")
                full_name = f"{first} {family}"
                player_aliases = [full_name, family]
                if "nameI" in row:
                    player_aliases.append(self._text(row["nameI"], f"{location}.nameI"))
                players[pid] = team_id
                aliases[pid] = player_aliases
                names[pid] = full_name
        for index, entry in enumerate(self._evidence.get("aliases", [])):
            location = f"evidence.aliases[{index}]"
            if not isinstance(entry, dict):
                raise self._error(f"{location} must be an object")
            pid = self._id(entry.get("player_id"), f"{location}.player_id")
            team_id = self._id(entry.get("team_id"), f"{location}.team_id")
            if pid not in players or players[pid] != team_id:
                raise self._error(
                    f"{location}: alias player/team is outside the box-score roster"
                )
            self._text(entry.get("source"), f"{location}.source")
            values = entry.get("names")
            if not isinstance(values, list) or not values:
                raise self._error(f"{location}.names must be a nonempty array")
            aliases[pid].extend(
                self._text(value, f"{location}.names") for value in values
            )
        roster = tuple(
            V3RosterPlayer(pid, tid, tuple(dict.fromkeys(aliases[pid])), names[pid])
            for pid, tid in players.items()
        )
        provenance = (
            f"{self._evidence['source']}; boxscore sha256={self.source_sha256}; "
            f"evidence {self.source.evidence_source} sha256={self.evidence_sha256}"
        )
        return V3GameContext(
            self.game_id,
            *teams,
            roster,
            self._evidence["roster_complete"],
            provenance,
            league_id=self.league_id,
            bench_people=self._bench_people(),
        )

    def _bench_people(self):
        entries = self._evidence.get("bench_people", [])
        if not isinstance(entries, list):
            raise self._error("evidence.bench_people must be an array")
        people = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise self._error("bench identity must be an object")
            people.append(
                V3BenchPerson(
                    self._id(entry.get("person_id"), "bench person_id"),
                    self._id(entry.get("team_id"), "bench team_id"),
                    self._text(entry.get("name"), "bench name"),
                    self._text(entry.get("source"), "bench source"),
                )
            )
        return tuple(people)

    def require_complete_roster(self):
        """Return context or explicitly reject insufficient coverage evidence."""
        if not self.context.roster_complete:
            raise self._error("complete roster evidence is missing")
        return self.context

    @property
    def source_data(self):
        """Defensive copy of the entire box-score response, including unknown fields."""
        return json_copy(self._source_data)

    @property
    def evidence(self):
        """Defensive copy of the sidecar, including per-alias sources."""
        return json_copy(self._evidence)
