"""Traceable participant facts, separate from enhanced events and statistics."""

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from pbpstats.data_loader.stats_nba_v3.association import (
    V3EventGroup,
    associate_actions,
)
from pbpstats.data_loader.stats_nba_v3.context import V3GameContext, _name_key
from pbpstats.data_loader.stats_nba_v3.jump_balls import V3JumpBallEvidence


@dataclass(frozen=True)
class V3Participant:
    status: str
    player_id: Optional[int] = None
    team_id: Optional[int] = None
    candidates: Tuple[int, ...] = ()
    source_indices: Tuple[int, ...] = ()
    evidence: str = ""
    name: Optional[str] = None
    external_sha256: Optional[str] = None


@dataclass(frozen=True)
class V3ParticipantEvent:
    group: V3EventGroup
    team_id: Optional[int]
    participants: Mapping[str, V3Participant]

    def __post_init__(self):
        object.__setattr__(
            self, "participants", MappingProxyType(dict(self.participants))
        )

    def require_player(self, role):
        """Refuse unknown/absent identities when a dependent operation needs a player."""
        result = self.participants.get(role)
        if (
            result is None
            or result.status not in ("explicit", "resolved")
            or result.player_id is None
        ):
            status = result.status if result else "not recorded"
            raise ValueError(
                f"Stats V3 game {self.group.primary.game_id}, source rows "
                f"{self.group.source_indices}: {role} is {status}"
            )
        return result.player_id


def _error(item, message):
    return ValueError(
        f"Stats V3 game {item.game_id}, source row {item.order}: {message}"
    )


def _id(item, field):
    value = item.data.get(field)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise _error(item, f"{field} must be a nonnegative integer")
    return value or None


class _Resolver:
    def __init__(self, context, snapshot_complete, jumps, rows=()):
        self.context = context
        self.snapshot_complete = snapshot_complete
        self.jumps = jumps
        self.substitution_aliases = {}
        if snapshot_complete and context.roster_complete:
            for row in rows:
                if row.action_type != "Substitution":
                    continue
                match = re.fullmatch(r"SUB: (.+) FOR (.+)", row.description)
                player = context.player(_id(row, "personId"))
                if not match or player is None:
                    continue
                team = self.team(row)
                known = context.candidates(match[2], team)
                if known and player.player_id not in known:
                    raise _error(row, "outgoing substitution name contradicts personId")
                key = (_name_key(match[2]), player.player_id)
                self.substitution_aliases.setdefault(key, []).append(row.order)

    def team(self, item):
        data = item.data
        person_id = (
            None
            if item.action_type in ("period", "Instant Replay")
            else _id(item, "personId")
        )
        team_id = _id(item, "teamId")
        candidates = set()
        if team_id is not None:
            if team_id not in self.context.team_ids:
                raise _error(item, "teamId is outside this game")
            candidates.add(team_id)
        if person_id in self.context.team_ids:
            candidates.add(person_id)
        player = self.context.player(person_id)
        if player is not None:
            candidates.add(player.team_id)
        bench = self.context.bench_person(person_id)
        if bench is not None:
            if not ((item.action_type == "Foul" and item.sub_type in ("Technical", "Double Technical"))
                    or (item.action_type == "Ejection" and item.sub_type == "Other")):
                raise _error(
                    item, "bench identity is only supported on a technical foul or ejection"
                )
            candidates.add(bench.team_id)
        location = data.get("location", "")
        if location not in (None, "", "h", "v"):
            raise _error(item, "unrecognized team location")
        if location in ("h", "v"):
            candidates.add(
                self.context.home_team_id
                if location == "h"
                else self.context.away_team_id
            )
        if len(candidates) > 1:
            raise _error(item, "teamId, personId, roster, or location disagree")
        return next(iter(candidates), None)

    def explicit(self, item, field, team_id=None):
        player_id = _id(item, field)
        if player_id is None:
            return None
        if player_id in self.context.team_ids:
            raise _error(item, f"{field} identifies a team, not a player")
        player = self.context.player(player_id)
        if self.context.roster_complete and player is None:
            raise _error(
                item, f"{field} player {player_id} is outside the complete roster"
            )
        if player is not None:
            if team_id is not None and player.team_id != team_id:
                raise _error(item, f"{field} conflicts with the participant's team")
            team_id = player.team_id
        return V3Participant(
            "explicit", player_id, team_id, source_indices=(item.order,), evidence=field
        )

    def named(self, item, name, team_id=None, field=None):
        candidates = self.context.candidates(name, team_id) if name else ()
        alias_rows = []
        additional = set()
        for (alias, pid), indices in self.substitution_aliases.items():
            if (name and alias == _name_key(name) and pid not in candidates
                    and (team_id is None or self.context.player(pid).team_id == team_id)):
                additional.add(pid)
                alias_rows.extend(indices)
        candidates = tuple(sorted(set(candidates) | additional))
        source_indices = tuple(sorted({item.order, *alias_rows}))
        explicit = self.explicit(item, field, team_id) if field else None
        if explicit is not None:
            if (
                self.context.roster_complete
                and candidates
                and explicit.player_id not in candidates
            ):
                raise _error(
                    item, f"{field} contradicts description participant {name!r}"
                )
            return explicit
        if name and team_id is None:
            # Only jump-ball recipients are intentionally searched across both teams.
            evidence = "description and both game rosters"
        else:
            evidence = "description and team roster"
        if alias_rows:
            evidence += "; name bound to explicit outgoing personId at substitution rows " + str(sorted(set(alias_rows)))
        if not self.context.roster_complete:
            status, evidence = "unresolved", "incomplete roster coverage"
        elif len(candidates) == 1:
            pid = candidates[0]
            return V3Participant(
                "resolved",
                pid,
                self.context.player(pid).team_id,
                candidates,
                source_indices,
                evidence,
                name,
            )
        else:
            status = "ambiguous" if len(candidates) > 1 else "unresolved"
        return V3Participant(
            status,
            team_id=team_id,
            candidates=candidates,
            source_indices=source_indices,
            evidence=evidence,
            name=name,
        )

    def actor(self, item, team_id):
        if item.action_type in ("period", "Instant Replay"):
            return V3Participant(
                "not_applicable",
                team_id=team_id,
                source_indices=(item.order,),
                evidence="administrative event; personId is not a player attribution",
            )
        person_id = _id(item, "personId")
        bench = self.context.bench_person(person_id)
        if bench is not None:
            label = "DOUBLE.TECHNICAL.FOUL" if item.sub_type == "Double Technical" else "T.FOUL"
            prefix = bench.name + (" Ejection:" if item.action_type == "Ejection" else " Foul:" + label)
            if not item.description.startswith(prefix):
                raise _error(
                    item, "technical foul description conflicts with bench identity"
                )
            return V3Participant(
                "not_applicable",
                team_id=bench.team_id,
                source_indices=(item.order,),
                name=bench.name,
                evidence=f"non-player personId {person_id}; {bench.source}",
            )
        if person_id in self.context.team_ids:
            return V3Participant(
                "not_applicable",
                team_id=team_id,
                source_indices=(item.order,),
                evidence="personId identifies the team",
            )
        explicit = self.explicit(item, "personId", team_id)
        if explicit is not None:
            return explicit
        no_player = (
            item.action_type == "Heave" and item.sub_type == "Team Field Goal Attempt"
        )
        return V3Participant(
            "not_applicable" if no_player else "unresolved",
            team_id=team_id,
            source_indices=(item.order,),
            evidence="team/administrative event" if no_player else "missing personId",
        )

    def secondary(self, group, actor, team_id, role):
        row = getattr(group, role)
        if row is None:
            return V3Participant(
                "absent" if self.snapshot_complete else "unresolved",
                source_indices=group.source_indices,
                evidence="no associated secondary row in a declared complete snapshot"
                if self.snapshot_complete
                else "no associated secondary row; snapshot completeness unverified",
            )
        secondary_team = self.team(row)
        if team_id is None or secondary_team != self.context.other_team(team_id):
            raise _error(row, f"{role} must belong to the opposing team")
        participant = self.explicit(row, "personId", secondary_team)
        if participant is None:
            # The 2025 team-heave feed zeros the blocker ID as well as the
            # shooter ID. Its opposing-team location and unique roster name
            # still provide an attributable block, without inventing a shooter.
            if role == "block" and group.primary.action_type == "Heave":
                match = re.fullmatch(r"(.+) BLOCK \([0-9]+ BLK\)", row.description)
                participant = self.named(row, match[1] if match else None, secondary_team)
            else:
                raise _error(row, f"{role} requires an explicit player ID")
        if participant.player_id == actor.player_id:
            raise _error(row, f"{role} cannot identify the primary actor")
        return participant

    def assister(self, item, team_id):
        description = item.data["description"]
        match = re.search(r"\(([^()]+) [0-9]+ AST\)$", description)
        if match or _id(item, "assistPersonId"):
            if team_id is None:
                return V3Participant(
                    "unresolved",
                    source_indices=(item.order,),
                    evidence="missing assisting team",
                )
            return self.named(
                item, match[1] if match else None, team_id, "assistPersonId"
            )
        ordinary_unassisted = (
            re.search(r"\([0-9]+ PTS\)$", description) and "AST" not in description
        )
        return V3Participant(
            "absent" if ordinary_unassisted else "unresolved",
            team_id=team_id,
            source_indices=(item.order,),
            evidence="no assist in recorded shot description"
            if ordinary_unassisted
            else "unrecognized shot description",
        )

    def substitution(self, item, actor, team_id):
        match = re.fullmatch(r"SUB: (.+) FOR (.+)", item.data["description"])
        if not match and team_id is not None:
            explicit = self.explicit(item, "incomingPersonId", team_id)
            if explicit is not None:
                return explicit
        if not match or team_id is None:
            return V3Participant(
                "unresolved",
                team_id=team_id,
                source_indices=(item.order,),
                evidence="unrecognized substitution description or missing team",
            )
        outgoing = self.context.candidates(match[2], team_id)
        if (
            self.context.roster_complete
            and actor.player_id is not None
            and outgoing
            and actor.player_id not in outgoing
        ):
            raise _error(item, "outgoing substitution name contradicts personId")
        return self.named(item, match[1], team_id, "incomingPersonId")

    def jump_ball(self, item, actor, team_id):
        if item.order in self.jumps:
            recovery = self.jumps[item.order]
            provenance = dict(
                source_indices=(item.order,),
                evidence=recovery.source,
                external_sha256=recovery.evidence_sha256,
            )
            return {
                "opposing_jumper": V3Participant(
                    "resolved",
                    recovery.opposing_jumper,
                    self.context.player(recovery.opposing_jumper).team_id,
                    **provenance,
                ),
                "tip_recipient": V3Participant(
                    "team", team_id=recovery.team_id, **provenance
                ),
            }
        match = re.fullmatch(
            r"Jump Ball (.+) vs\. (.+): Tip to (.+)", item.data["description"]
        )
        if not match or team_id is None:
            unknown = V3Participant(
                "unresolved",
                source_indices=(item.order,),
                evidence="unrecognized jump-ball description or missing team",
            )
            return {"opposing_jumper": unknown, "tip_recipient": unknown}
        first = self.context.candidates(match[1], team_id)
        if (
            self.context.roster_complete
            and actor.player_id is not None
            and first
            and actor.player_id not in first
        ):
            raise _error(item, "first jump-ball participant contradicts personId")
        return {
            "opposing_jumper": self.named(
                item, match[2], self.context.other_team(team_id)
            ),
            "tip_recipient": self.named(item, match[3]),
        }

    def double_foul(self, item, actor, team_id):
        if item.sub_type == "Double Personal":
            pattern = r"\s*Foul\s*:\s*Double Personal - (.+) \([0-9]+ PF\), (.+) \([0-9]+ PF\) \([^()]+\)"
        else:
            pattern = r"Double Technical - (.+), (.+) \([^()]+\)"
        match = re.fullmatch(pattern, item.description)
        if not match or team_id is None:
            return V3Participant("unresolved", source_indices=(item.order,),
                                 evidence="double-foul opponent is not identified by a supported description")
        if actor.player_id not in self.context.candidates(match[1], team_id):
            raise _error(item, "double-foul first name conflicts with personId")
        return self.named(item, match[2], self.context.other_team(team_id))

    def resolve(self, group):
        item = group.primary
        team_id = self.team(item)
        actor = self.actor(item, team_id)
        roles = {"actor": actor}
        if item.action_type == "Made Shot":
            roles["assister"] = self.assister(item, team_id)
        elif item.action_type == "Missed Shot" or (item.action_type == "Heave" and group.block is not None):
            roles["blocker"] = self.secondary(group, actor, team_id, "block")
        elif item.action_type == "Turnover":
            roles["stealer"] = self.secondary(group, actor, team_id, "steal")
        elif item.action_type == "Substitution":
            roles["outgoing"] = actor
            roles["incoming"] = self.substitution(item, actor, team_id)
        elif item.action_type == "Jump Ball":
            roles.update(self.jump_ball(item, actor, team_id))
        elif item.action_type == "Foul":
            if item.sub_type in ("Double Personal", "Double Technical"):
                roles["other_fouler"] = self.double_foul(item, actor, team_id)
            roles["foul_drawn"] = self.explicit(
                item,
                "foulDrawnPersonId",
                self.context.other_team(team_id) if team_id else None,
            ) or V3Participant(
                "unresolved",
                source_indices=(item.order,),
                evidence="no explicit foul-drawn identity; clock matching alone is insufficient",
            )
        for role in ("assister", "incoming", "opposing_jumper", "foul_drawn"):
            participant = roles.get(role)
            if (
                participant
                and participant.player_id is not None
                and participant.player_id == actor.player_id
            ):
                raise _error(item, f"{role} cannot be the primary actor")
        return V3ParticipantEvent(group, team_id, roles)


class StatsNbaV3ParticipantLoader:
    """Associate raw rows and resolve participant roles with explicit context.

    Unknown identities remain structured results. Call ``require_player`` before
    an operation that requires an identified player. This is not a lineup or
    possession loader and makes no claim that a snapshot is complete.
    """

    def __init__(
        self, pbp_loader, context, *, snapshot_complete=False, jump_ball_evidence=None
    ):
        if not isinstance(context, V3GameContext):
            raise TypeError("context must be a V3GameContext")
        if context.game_id != pbp_loader.game_id:
            raise ValueError("PBP and game context have different game IDs")
        if type(snapshot_complete) is not bool:
            raise ValueError("snapshot_complete must be a boolean")
        self.game_id = pbp_loader.game_id
        self.context = context
        self.snapshot_complete = snapshot_complete
        if jump_ball_evidence is not None and not isinstance(
            jump_ball_evidence, V3JumpBallEvidence
        ):
            raise TypeError("jump_ball_evidence must be V3JumpBallEvidence")
        self.jump_ball_evidence = jump_ball_evidence
        jumps = (
            jump_ball_evidence.bind(pbp_loader, context)
            if jump_ball_evidence is not None
            else {}
        )
        resolver = _Resolver(context, snapshot_complete, jumps, pbp_loader.items)
        self.items = tuple(
            resolver.resolve(group) for group in associate_actions(pbp_loader.items)
        )
