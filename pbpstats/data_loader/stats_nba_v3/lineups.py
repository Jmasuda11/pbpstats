"""Evidence-bound, atomic lineup transitions; no implicit starter inference."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Tuple

from pbpstats.data_loader.stats_nba_v3.classification import (
    StatsNbaV3EventLoader,
    V3ClassifiedEvent,
)
from pbpstats.data_loader.stats_nba_v3.pbp.file import (
    _finite_float,
    _reject_constant,
    _unique_object,
)
from pbpstats.resources.json_copy import json_copy


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def lineup_fingerprints(event_loader):
    """Identify semantic inputs; these hashes are not original-file checksums.

    Computing a fingerprint does not establish starter or batch evidence.
    """
    if not isinstance(event_loader, StatsNbaV3EventLoader):
        raise TypeError("lineup_fingerprints requires StatsNbaV3EventLoader")
    context = event_loader.context
    roster = dict(
        game_id=context.game_id,
        home=context.home_team_id,
        away=context.away_team_id,
        complete=context.roster_complete,
        source=context.roster_source,
        players=[
            dict(id=p.player_id, team=p.team_id, name=p.name, aliases=p.aliases)
            for p in context.players
        ],
    )
    events = [
        dict(
            kind=e.kind,
            rows=[dict(index=r.order, data=r.data) for r in e.group.rows],
            participants={
                role: dict(
                    status=p.status,
                    player=p.player_id,
                    team=p.team_id,
                    **(
                        {"external_sha256": p.external_sha256}
                        if p.external_sha256
                        else {}
                    ),
                )
                for role, p in e.participants.participants.items()
            },
        )
        for e in event_loader.items
    ]
    if context.bench_people:
        roster["bench_people"] = [
            dict(person_id=p.person_id, team_id=p.team_id, name=p.name, source=p.source)
            for p in context.bench_people
        ]
    return {"context_sha256": _digest(roster), "snapshot_sha256": _digest(events)}


class V3LineupEvidence:
    """Decode evidence bytes, retaining the original bytes and source location."""

    def __init__(self, raw, source):
        if not isinstance(source, str) or not source.strip():
            raise ValueError("lineup evidence requires a source location")
        self.source = source
        if not isinstance(raw, bytes):
            raise TypeError("lineup evidence requires bytes")
        try:
            self._data = json_copy(
                json.loads(
                    raw.decode("utf-8-sig"),
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                    parse_float=_finite_float,
                )
            )
        except (ValueError, RecursionError) as error:
            raise ValueError(f"Lineup evidence {source}: {error}") from error
        if not isinstance(self._data, dict):
            raise ValueError(f"Lineup evidence {source}: expected an object")
        self.source_bytes = raw
        self.sha256 = hashlib.sha256(raw).hexdigest()

    @classmethod
    def from_file(cls, path):
        path = Path(path)
        return cls(path.read_bytes(), str(path))

    @property
    def data(self):
        return json_copy(self._data)


def _freeze_lineups(lineups):
    return MappingProxyType(
        {team: tuple(sorted(players)) for team, players in lineups.items()}
    )


@dataclass(frozen=True)
class V3LineupEvent:
    event: V3ClassifiedEvent
    before: Mapping[int, Tuple[int, ...]]
    after: Mapping[int, Tuple[int, ...]]
    batch_source_indices: Tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "before", _freeze_lineups(self.before))
        object.__setattr__(self, "after", _freeze_lineups(self.after))


class StatsNbaV3LineupLoader:
    """Apply reviewed starters and substitution batches to classified events.

    Both complete-roster and complete-snapshot declarations are required, and
    every represented period needs its own starters. No field on a box score
    or prior-period ending lineup supplies them implicitly. Evidence provenance
    is retained, but a caller's external assertions cannot be authenticated.
    """

    def __init__(self, event_loader, evidence):
        if not isinstance(event_loader, StatsNbaV3EventLoader):
            raise TypeError("lineup loader requires StatsNbaV3EventLoader")
        if not isinstance(evidence, V3LineupEvidence):
            raise TypeError("lineup loader requires V3LineupEvidence")
        self.game_id = event_loader.game_id
        self.context = event_loader.context
        self.rules = self.context.rules
        self.evidence = evidence
        self._events = event_loader.items
        if not self.context.roster_complete or not event_loader.snapshot_complete:
            raise self._error("complete roster and snapshot evidence are required")
        data = evidence.data
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise self._error("schema_version must be 1")
        if data.get("game_id") != self.game_id:
            raise self._error("evidence game_id conflicts with events")
        for key, expected in lineup_fingerprints(event_loader).items():
            if data.get(key) != expected:
                raise self._error(f"{key} does not match lineup inputs")
        periods = self._validate_periods()
        starters = self._starters(data.get("periods"), periods)
        batches = self._batches(data.get("batches"))
        self.items = self._reconstruct(starters, batches)
        self._validate_ejections()

    def _error(self, message, event=None):
        position = f", source rows {event.group.source_indices}" if event else ""
        return ValueError(
            f"Stats V3 game {self.game_id}{position}, lineup evidence {self.evidence.source}: {message}"
        )

    def _provenance(self, record, label):
        value = record.get("source")
        if not isinstance(value, str) or not value.strip():
            raise self._error(f"{label} requires source provenance")

    def _validate_periods(self):
        periods = []
        active = None
        previous_clock = None
        for event in self._events:
            row = event.group.primary
            clock = row.seconds_remaining_exact
            if event.kind == "period_start":
                if active is not None or row.period != len(periods) + 1:
                    raise self._error(
                        "missing, repeated, or out-of-order period boundary", event
                    )
                if self.rules.untimed(row.period) and row.period != 5:
                    raise self._error(
                        "target-score overtime has exactly one period", event
                    )
                if clock != self.rules.opening_clock(row.period):
                    raise self._error("period start is not at the opening clock", event)
                periods.append(row.period)
                active = row.period
                previous_clock = clock
            elif active is None or row.period != active:
                raise self._error("event lies outside a started period", event)
            if clock > previous_clock:
                raise self._error("clock increases within a period", event)
            previous_clock = clock
            if event.kind == "period_end":
                if clock != 0 and not self.rules.untimed(row.period):
                    raise self._error("period end is not at zero", event)
                active = None
        if not periods or active is not None:
            raise self._error("complete period boundaries are required")
        return set(periods)

    def _starters(self, records, periods):
        if not isinstance(records, list):
            raise self._error("periods must be an array of starter evidence")
        result = {}
        for record in records:
            if not isinstance(record, dict):
                raise self._error("starter record must be an object")
            period = record.get("period")
            if type(period) is not int or period not in periods or period in result:
                raise self._error("duplicate or extraneous starter period")
            self._provenance(record, f"period {period} starters")
            lineups = {}
            for side, team in zip(("home", "away"), self.context.team_ids):
                players = record.get(side)
                if (
                    not isinstance(players, list)
                    or len(players) != 5
                    or any(type(p) is not int or p <= 0 for p in players)
                    or len(set(players)) != 5
                ):
                    raise self._error(
                        f"period {period} {side} requires five distinct player IDs"
                    )
                if any(
                    self.context.player(p) is None
                    or self.context.player(p).team_id != team
                    for p in players
                ):
                    raise self._error(
                        f"period {period} {side} starter conflicts with roster"
                    )
                lineups[team] = set(players)
            result[period] = lineups
        if set(result) != periods:
            raise self._error(
                f"missing period starters: {sorted(periods - set(result))}"
            )
        return result

    def _batches(self, records):
        if not isinstance(records, list):
            raise self._error("batches must be an array")
        by_source = {e.group.primary.order: i for i, e in enumerate(self._events)}
        substitutions = {
            e.group.primary.order for e in self._events if e.kind == "substitution"
        }
        covered, result = set(), {}
        for record in records:
            if not isinstance(record, dict):
                raise self._error("batch record must be an object")
            self._provenance(record, "substitution batch")
            indices = record.get("source_indices")
            if (
                not isinstance(indices, list)
                or not indices
                or any(type(i) is not int or i < 0 for i in indices)
            ):
                raise self._error("batch requires nonempty primary source_indices")
            if (
                len(set(indices)) != len(indices)
                or set(indices) & covered
                or not set(indices) <= substitutions
            ):
                raise self._error(
                    "batch contains repeated or non-substitution source indices"
                )
            positions = [by_source[index] for index in indices]
            if positions != list(range(positions[0], positions[0] + len(positions))):
                raise self._error(
                    "batch must be contiguous substitutions in source order"
                )
            events = [self._events[i] for i in positions]
            if (
                len(
                    {
                        (
                            e.group.primary.period,
                            e.group.primary.seconds_remaining_exact,
                        )
                        for e in events
                    }
                )
                != 1
            ):
                raise self._error("batch has conflicting period or exact clock")
            covered.update(indices)
            result[positions[0]] = tuple(events)
        if covered != substitutions:
            raise self._error(
                f"missing substitution batch evidence: {sorted(substitutions - covered)}"
            )
        return result

    def _substitute(self, batch, before):
        outgoing = {t: set() for t in self.context.team_ids}
        incoming = {t: set() for t in self.context.team_ids}
        for event in batch:
            team = event.team_id
            if team not in before:
                raise self._error("substitution requires a game team", event)
            removed = event.participants.require_player("outgoing")
            added = event.participants.require_player("incoming")
            if removed in outgoing[team] or added in incoming[team]:
                raise self._error(
                    "duplicate outgoing or incoming player in batch", event
                )
            if removed not in before[team] or added in before[team]:
                raise self._error(
                    "outgoing player absent or incoming player already on court", event
                )
            if (
                self.context.player(added) is None
                or self.context.player(added).team_id != team
            ):
                raise self._error("incoming player conflicts with roster", event)
            outgoing[team].add(removed)
            incoming[team].add(added)
        after = {t: (before[t] - outgoing[t]) | incoming[t] for t in before}
        if any(len(players) != 5 for players in after.values()):
            raise self._error("substitution batch does not leave five players per team")
        return after

    def _validate_on_court(self, event, lineups):
        if event.kind in (
            "period_start",
            "period_end",
            "replay",
            "timeout",
            "ejection",
        ):
            return
        # Technicals can identify bench personnel; they do not establish who is
        # on court. Do not use them to infer starters or force a substitution.
        if (
            event.kind == "foul" and event.subtype in ("Technical", "Hanging Technical")
        ) or (event.free_throw and event.free_throw.category == "technical"):
            return
        roles = event.participants.participants
        if (
            event.kind
            in ("field_goal", "free_throw", "rebound", "turnover", "foul", "jump_ball")
            and roles["actor"].status != "not_applicable"
        ):
            event.participants.require_player("actor")
        if event.kind == "jump_ball":
            event.participants.require_player("opposing_jumper")
            recipient = roles["tip_recipient"]
            if recipient.status != "team":
                event.participants.require_player("tip_recipient")
            elif (
                recipient.team_id not in lineups
                or recipient.player_id is not None
                or not recipient.external_sha256
            ):
                raise self._error(
                    "team jump recovery requires separate validated evidence", event
                )
        for role, player in roles.items():
            if player.player_id is not None and (
                player.team_id not in lineups
                or player.player_id not in lineups[player.team_id]
            ):
                raise self._error(
                    f"{role} player {player.player_id} is not on court", event
                )

    def _validate_ejections(self):
        ejected = {}
        for item in self.items:
            event = item.event
            stamp = (
                event.group.primary.period,
                event.group.primary.seconds_remaining_exact,
            )
            if event.kind == "ejection":
                pid = event.participants.require_player("actor")
                if self.context.player(pid) is None or pid in ejected:
                    raise self._error(
                        "ejection requires a roster player not already ejected", event
                    )
                ejected[pid] = stamp
                continue
            for role, participant in event.participants.participants.items():
                if participant.player_id in ejected and not (
                    event.kind == "substitution" and role in ("actor", "outgoing")
                ):
                    raise self._error(
                        "ejected player cannot participate or re-enter", event
                    )
            for players in item.before.values():
                for pid in set(players) & ejected.keys():
                    if ejected[pid] != stamp or event.kind not in (
                        "substitution",
                        "replay",
                        "timeout",
                        "period_end",
                    ):
                        raise self._error(
                            "ejected player requires explicit replacement before further play",
                            event,
                        )

    def _reconstruct(self, starters, batches):
        result, position, lineups = [], 0, None
        while position < len(self._events):
            event = self._events[position]
            if event.kind == "period_start":
                lineups = {
                    t: set(players)
                    for t, players in starters[event.group.primary.period].items()
                }
            if position in batches:
                batch = batches[position]
                after = self._substitute(batch, lineups)
                indices = tuple(e.group.primary.order for e in batch)
                result.extend(V3LineupEvent(e, lineups, after, indices) for e in batch)
                lineups = after
                position += len(batch)
            else:
                self._validate_on_court(event, lineups)
                result.append(V3LineupEvent(event, lineups, lineups))
                position += 1
        return tuple(result)
