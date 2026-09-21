"""Offline, per-shot validation of official live-feed three-point zones."""

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Optional, Tuple

from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.lineups import lineup_fingerprints
from pbpstats.data_loader.stats_nba_v3.pbp.file import (
    _finite_float,
    _reject_constant,
    _unique_object,
)
from pbpstats.resources.json_copy import json_copy
from pbpstats.resources.period_clock import parse_period_clock

AREAS = {
    "Left Corner 3": "Corner3",
    "Right Corner 3": "Corner3",
    "Above the Break 3": "Arc3",
}
DETAILS = {
    **AREAS,
    "24+ Left": "Corner3",
    "24+ Right": "Corner3",
    "24+ Center": "Arc3",
    "24+ Left Center": "Arc3",
    "24+ Right Center": "Arc3",
}
CORNER_SIDES = {
    "Left Corner 3": "left",
    "Right Corner 3": "right",
    "24+ Left": "left",
    "24+ Right": "right",
}


class V3LiveShotEvidence:
    """Retain exact live response bytes, their digest and supplied provenance.

    A source label records the caller's provenance assertion, not independent
    authentication. This class never fetches data or repairs source rows.
    """

    def __init__(self, raw, source):
        if not isinstance(source, str) or not source.strip():
            raise ValueError("live shot evidence requires source provenance")
        if not isinstance(raw, bytes):
            raise TypeError("live shot evidence requires bytes")
        try:
            data = json_copy(
                json.loads(
                    raw.decode("utf-8-sig"),
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                    parse_float=_finite_float,
                )
            )
        except (ValueError, RecursionError) as error:
            raise ValueError(f"Live shot evidence {source}: {error}") from error
        if not isinstance(data, dict):
            raise ValueError(f"Live shot evidence {source}: expected an object")
        self.source, self.source_bytes = source, raw
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self._data = data

    @classmethod
    def from_file(cls, path, *, source=None):
        path = Path(path)
        return cls(path.read_bytes(), str(path) if source is None else source)

    @property
    def data(self):
        return json_copy(self._data)


@dataclass(frozen=True)
class V3ShotZone:
    source_index: int
    action_number: int
    area: Optional[str]
    area_detail: Optional[str]
    shot_type: Optional[str]
    issues: Tuple[str, ...]

    @property
    def validated(self):
        return not self.issues


def _clock(value):
    if not isinstance(value, str):
        return None
    parsed = parse_period_clock(value)
    return parsed[1] if parsed is not None and parsed[0] < 60 else None


def _finite(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


class StatsNbaV3ShotZoneLoader:
    """Bind live zone labels to a classified native V3 snapshot.

    All native three-point attempts receive a result. Missing, unsupported or
    conflicting evidence remains inspectable in ``items`` and raises when its
    zone is requested; ``require_complete`` rejects any unresolved attempt.
    Structural ambiguity (including duplicate action numbers) fails at load.
    Two-point zones and team heaves are outside this contract.
    """

    def __init__(self, event_loader, evidence):
        if not isinstance(event_loader, StatsNbaV3EventLoader):
            raise TypeError("shot zones require StatsNbaV3EventLoader")
        if not isinstance(evidence, V3LiveShotEvidence):
            raise TypeError("shot zones require V3LiveShotEvidence")
        self.game_id = event_loader.game_id
        self.league_id = event_loader.context.league_id
        self.evidence = evidence
        self.fingerprints = MappingProxyType(lineup_fingerprints(event_loader))
        game = evidence.data.get("game")
        if not isinstance(game, dict) or game.get("gameId") != self.game_id:
            raise self._error("live gameId conflicts with native snapshot")
        actions = game.get("actions")
        if not isinstance(actions, list):
            raise self._error("live actions must be an array")
        live = self._index(actions, "live")
        native = self._index(
            [e.group.primary.data for e in event_loader.items], "native"
        )
        # Extra live shots may reflect a stale or unrelated snapshot; never
        # silently discard them. Matching rows are checked individually below.
        for number, action in live.items():
            if action.get("actionType") == "3pt" and number not in native:
                raise self._error(f"extraneous live three-point actionNumber {number}")
        results = []
        for event in event_loader.items:
            if event.kind == "field_goal" and event.shot_value == 3:
                row = event.group.primary
                results.append(self._match(event, live.get(row.action_number)))
            elif row_is_three(live.get(event.group.primary.action_number)):
                raise self._error(
                    f"live three-point actionNumber {event.group.primary.action_number} "
                    "conflicts with native event kind/shot value"
                )
        self.items = tuple(results)
        self.by_source_index = MappingProxyType({r.source_index: r for r in results})

    def _error(self, message):
        return ValueError(
            f"Stats V3 game {self.game_id}, shot zones {self.evidence.source}: {message}"
        )

    def _index(self, actions, label):
        result = {}
        for action in actions:
            if not isinstance(action, dict):
                raise self._error(f"{label} action must be an object")
            number = action.get("actionNumber")
            if type(number) is not int or number < 0 or number in result:
                raise self._error(
                    f"{label} invalid or duplicate actionNumber {number!r}"
                )
            result[number] = action
        return result

    def _match(self, event, action):
        row = event.group.primary
        issues = []
        if action is None:
            return V3ShotZone(
                row.order, row.action_number, None, None, None, ("missing live shot",)
            )
        expected = dict(
            period=row.period,
            teamId=event.team_id,
            personId=event.participants.require_player("actor"),
            isFieldGoal=1,
            actionType="3pt",
            shotResult="Made" if event.is_made else "Missed",
        )
        for field, value in expected.items():
            if type(action.get(field)) is not type(value) or action[field] != value:
                issues.append(f"{field} conflicts with native shot")
        if _clock(action.get("clock")) != row.seconds_remaining_exact:
            issues.append("clock conflicts with native shot")
        for field in ("xLegacy", "yLegacy"):
            value, native = action.get(field), row.get(field)
            if not _finite(value) or not _finite(native):
                issues.append(f"{field} requires finite coordinates in both sources")
            elif value != native:
                issues.append(f"{field} conflicts with native shot")
        area, detail = action.get("area"), action.get("areaDetail")
        area = area if isinstance(area, str) else None
        detail = detail if isinstance(detail, str) else None
        zone, detail_zone = AREAS.get(area), DETAILS.get(detail)
        if zone is None:
            issues.append("area is missing or unsupported for a three-point shot")
        if detail_zone is None:
            issues.append("areaDetail is missing or unsupported for a three-point shot")
        elif zone is not None and (
            zone != detail_zone
            or zone == "Corner3"
            and CORNER_SIDES[area] != CORNER_SIDES[detail]
        ):
            issues.append("area and areaDetail conflict")
        return V3ShotZone(
            row.order,
            row.action_number,
            area,
            detail,
            zone if not issues else None,
            tuple(issues),
        )

    def require_zone(self, source_index):
        if type(source_index) is not int:
            raise self._error("source row index must be an integer")
        result = self.by_source_index.get(source_index)
        if result is None:
            raise self._error(
                f"source row {source_index}: no three-point zone evidence"
            )
        if result.issues:
            raise self._error(f"source row {source_index}: {'; '.join(result.issues)}")
        return result.shot_type

    def require_complete(self):
        for result in self.items:
            self.require_zone(result.source_index)
        return self

    def validate_lineups(self, lineups):
        """Reject attachment to a different classified snapshot or game context."""
        # The lineup loader already verified these fingerprints at construction.
        data = lineups.evidence.data
        if lineups.game_id != self.game_id or any(
            data.get(key) != value for key, value in self.fingerprints.items()
        ):
            raise self._error("shot-zone fingerprints do not match lineup inputs")


def row_is_three(action):
    return action is not None and action.get("actionType") == "3pt"
