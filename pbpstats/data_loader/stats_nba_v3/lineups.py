"""Evidence-bound, atomic lineup transitions; no implicit starter inference."""

import hashlib
import json
from dataclasses import dataclass, replace
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
from pbpstats.data_loader.stats_nba_v3.v2_rules import period_order, technical_activity


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

    def __init__(self, event_loader, evidence, *, use_v2_rules=False):
        if not isinstance(event_loader, StatsNbaV3EventLoader):
            raise TypeError("lineup loader requires StatsNbaV3EventLoader")
        if not isinstance(evidence, V3LineupEvidence):
            raise TypeError("lineup loader requires V3LineupEvidence")
        self.game_id = event_loader.game_id
        self.context = event_loader.context
        self.rules = self.context.rules
        self.evidence = evidence
        self.use_v2_rules = use_v2_rules
        self.diagnostics = []
        self._implied_jump_winners = {}
        self._events = event_loader.items
        if not self.context.roster_complete or not event_loader.snapshot_complete:
            raise self._error("complete roster and snapshot evidence are required")
        data = evidence.data
        if data.get("processing_rules") not in (None, "strict", "v2"):
            raise self._error("unknown processing_rules in lineup evidence")
        if data.get("processing_rules") == "v2" and not use_v2_rules:
            raise self._error("lineup evidence requires use_v2_rules=True")
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise self._error("schema_version must be 1")
        if data.get("game_id") != self.game_id:
            raise self._error("evidence game_id conflicts with events")
        for key, expected in lineup_fingerprints(event_loader).items():
            if data.get(key) != expected:
                raise self._error(f"{key} does not match lineup inputs")
        if use_v2_rules:
            indices, self.diagnostics = period_order(
                ((e.group.primary.order, e.group.primary.data) for e in self._events), self.rules
            )
            by_index = {e.group.primary.order: e for e in self._events}
            self._events = tuple(by_index[i] for i in indices)
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
                if not (active is None and periods and row.period == periods[-1]
                        and event.kind == "replay" and clock == previous_clock):
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

    @staticmethod
    def _requires_on_court_participants(event):
        if event.kind in (
            "period_start",
            "period_end",
            "replay",
            "timeout",
            "ejection",
        ):
            return False
        # Technicals can identify bench personnel; they do not establish who is
        # on court. Do not use them to infer starters or force a substitution.
        if (
            event.kind == "foul" and event.subtype in (
                "Technical", "Hanging Technical", "Double Technical", "Delay Technical", "Bench",
                "Excess Timeout Technical", "Too Many Players Technical", "Non-Unsportsmanlike Technical",
            )
        ) or (event.free_throw and event.free_throw.category == "technical"):
            return False
        return True

    def _resolve_on_court_names(self, event, lineups):
        """Narrow name-only candidates using this event's validated lineup.

        Roster facts and their review fingerprints stay unchanged. These
        derived identities belong to the lineup result consumed by possessions.
        Substitutions use their separate entrance/exit validation, so incoming
        bench players are never excluded by this on-court filter.
        """
        if not self._requires_on_court_participants(event):
            return event
        roles = dict(event.participants.participants)
        changed = False
        for role, participant in roles.items():
            if (
                participant.status not in ("ambiguous", "unresolved")
                or not participant.name
            ):
                continue
            candidates = tuple(
                pid for pid in participant.candidates
                if pid in lineups.get(self.context.player(pid).team_id, ())
                and (
                    participant.team_id is None
                    or self.context.player(pid).team_id == participant.team_id
                )
            )
            if candidates == participant.candidates:
                continue
            player_id = candidates[0] if len(candidates) == 1 else None
            if (
                player_id is not None
                and role in ("assister", "opposing_jumper", "foul_drawn")
                and player_id == roles["actor"].player_id
            ):
                raise self._error(f"{role} cannot be the primary actor", event)
            roles[role] = replace(
                participant,
                status="resolved"
                if player_id is not None
                else "ambiguous"
                if candidates
                else "unresolved",
                player_id=player_id,
                team_id=self.context.player(player_id).team_id
                if player_id is not None
                else participant.team_id,
                candidates=candidates,
                evidence=(
                    participant.evidence
                    + "; name candidates restricted to players on court before "
                    f"source row {event.group.primary.order}; "
                    f"lineup evidence sha256={self.evidence.sha256}"
                ),
            )
            changed = True
        if self.use_v2_rules and event.kind == "jump_ball":
            recipient = roles["tip_recipient"]
            teams = {self.context.player(pid).team_id for pid in recipient.candidates}
            if recipient.status == "ambiguous" and len(teams) == 1:
                roles["tip_recipient"] = replace(
                    recipient, team_id=next(iter(teams)),
                    evidence=recipient.evidence + "; all on-court recipient candidates belong to the same team; individual identity remains ambiguous",
                )
                changed = True
        if not changed:
            return event
        return replace(
            event, participants=replace(event.participants, participants=roles)
        )

    def _infer_jump_winner(self, event, position):
        """Infer only the recovering team from the first clear control event.

        This assumes the declared complete snapshot has no unrecorded change
        of control. Retain the unknown individual and cite every traversed row.
        A same-clock turnover can describe the loss *leading to* the jump, so
        it cannot establish the team that controlled the ball after the tip.
        """
        if not self.use_v2_rules or event.kind != "jump_ball":
            return event
        recipient = event.participants.participants["tip_recipient"]
        if recipient.status not in ("unresolved", "ambiguous") or recipient.team_id is not None:
            return event
        row = event.group.primary
        if self.rules.untimed(row.period):
            return event
        indices = list(event.group.source_indices)
        for witness in self._events[position + 1:]:
            following = witness.group.primary
            elapsed = row.seconds_remaining_exact - following.seconds_remaining_exact
            # A single bounded stretch of play; never cross a period or skip
            # a second jump, rebound, free throw, violation or unknown foul.
            if following.period != row.period or not 0 <= elapsed <= 24:
                break
            indices.extend(witness.group.source_indices)
            if witness.kind in ("substitution", "timeout"):
                continue
            team = witness.team_id
            if team not in self.context.team_ids:
                break
            if witness.kind == "field_goal":
                pass
            elif witness.kind == "turnover" and elapsed > 0 and witness.subtype in (
                "Bad Pass", "Lost Ball", "Traveling", "Double Dribble", "Palming Turnover",
                "Discontinue Dribble", "3 Second Violation", "5 Second Violation",
                "8 Second Violation", "10 Second Violaton", "Backcourt Turnover",
                "Out of Bounds - Bad Pass Turnover", "Out of Bounds Lost Ball Turnover",
                "Step Out of Bounds Turnover", "Shot Clock Turnover", "Offensive Foul Turnover",
            ):
                pass  # Use the team losing control, not the stealing team.
            elif witness.kind == "foul" and elapsed > 0 and witness.subtype in (
                "Offensive", "Offensive Charge", "Shooting",
            ):
                if witness.subtype == "Shooting":
                    team = self.context.other_team(team)
            else:
                break
            # A named recipient with no on-court matches cannot be repaired
            # by assigning a team; nor can a contradicting candidate list.
            if recipient.name and not any(
                self.context.player(pid).team_id == team for pid in recipient.candidates
            ):
                break
            source_indices = tuple(dict.fromkeys(indices))
            explanation = (
                f"Implied jump recovery team {team} from subsequent {witness.kind}"
                f"/{witness.subtype} at source rows {witness.group.source_indices}; "
                "only substitutions/timeouts intervened; assumes complete event order; "
                "individual tip recipient remains unknown"
            )
            roles = dict(event.participants.participants)
            roles["tip_recipient"] = replace(
                recipient, team_id=team, source_indices=source_indices,
                evidence=recipient.evidence + "; " + explanation,
            )
            self._implied_jump_winners[row.order] = team
            self.diagnostics.append(dict(
                stage="participants", code="implied_jump_winner",
                message=explanation, source_indices=source_indices,
            ))
            return replace(event, participants=replace(event.participants, participants=roles))
        return event

    def _validate_on_court(self, event, lineups):
        if not self._requires_on_court_participants(event):
            return
        roles = event.participants.participants
        if event.kind == "foul" and event.subtype == "Double Personal":
            event.participants.require_player("other_fouler")
        if (
            event.kind
            in ("field_goal", "free_throw", "rebound", "turnover", "foul", "jump_ball")
            and roles["actor"].status != "not_applicable"
        ):
            event.participants.require_player("actor")
        if event.kind == "jump_ball":
            opponent = roles["opposing_jumper"]
            if not self.use_v2_rules or opponent.status not in ("unresolved", "ambiguous"):
                event.participants.require_player("opposing_jumper")
            else:
                # V2 possession rules use the winning TEAM, not both jumpers'
                # identities. Preserve the explicit actor and unknown opponent.
                self.diagnostics.append(dict(
                    stage="participants", code="unknown_opposing_jumper",
                    message="Recorded jump actor retained; opposing jumper remains unknown and is not needed for team possession accounting.",
                    source_indices=event.group.source_indices,
                ))
            recipient = roles["tip_recipient"]
            inferred_team = (self.use_v2_rules and recipient.team_id is not None
                             and self._implied_jump_winners.get(event.group.primary.order) == recipient.team_id)
            known_team_only = (self.use_v2_rules and recipient.status == "ambiguous"
                               and recipient.candidates and recipient.team_id in lineups
                               and all(self.context.player(pid).team_id == recipient.team_id
                                       for pid in recipient.candidates))
            if self.use_v2_rules and recipient.status in ("unresolved", "ambiguous") and not (known_team_only or inferred_team):
                raise self._error(
                    "jump-ball winning team is unresolved; the recorded actor ID does not identify who recovered the ball", event
                )
            if inferred_team:
                pass  # Provenance and a notice were recorded by look-ahead.
            elif known_team_only:
                self.diagnostics.append(dict(
                    stage="participants", code="ambiguous_recipient_known_team",
                    message="All on-court tip-recipient candidates share a team; use that team for possession, retaining the unresolved individual identity.",
                    source_indices=event.group.source_indices,
                ))
            elif recipient.status != "team":
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
        ejected_bench = set()
        for item in self.items:
            event = item.event
            bench = self.context.bench_person(event.group.primary.get("personId"))
            if bench is not None:
                if bench.person_id in ejected_bench:
                    raise self._error("ejected bench person cannot participate again", event)
                if event.kind == "ejection":
                    ejected_bench.add(bench.person_id)
                    continue
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
                    or self.use_v2_rules and ejected[participant.player_id] == stamp
                    and event.kind == "foul" and technical_activity(event.group.primary.data)
                ):
                    raise self._error(
                        "ejected player cannot participate or re-enter", event
                    )
            for players in item.before.values():
                for pid in set(players) & ejected.keys():
                    administrative = self.use_v2_rules and technical_activity(event.group.primary.data)
                    if ejected[pid] != stamp or not (administrative or event.kind in (
                        "substitution",
                        "replay",
                        "timeout",
                        "period_end",
                    )):
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
                event = self._resolve_on_court_names(event, lineups)
                event = self._infer_jump_winner(event, position)
                self._validate_on_court(event, lineups)
                result.append(V3LineupEvent(event, lineups, lineups))
                position += 1
        return tuple(result)
