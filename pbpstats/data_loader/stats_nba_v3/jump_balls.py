"""Reviewed, byte-bound live evidence for native jumps with blank descriptions."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pbpstats.data_loader.stats_nba_v3.pbp.file import (
    _finite_float,
    _reject_constant,
    _unique_object,
)
from pbpstats.resources.json_copy import json_copy
from pbpstats.resources.period_clock import parse_period_clock


def _decode(raw):
    if not isinstance(raw, bytes):
        raise TypeError("jump-ball evidence requires bytes")
    try:
        value = json_copy(
            json.loads(
                raw.decode("utf-8-sig"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
        )
    except (ValueError, RecursionError) as error:
        raise ValueError(f"invalid jump-ball evidence JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("jump-ball evidence requires JSON objects")
    return value


def _clock(value):
    parsed = parse_period_clock(value) if isinstance(value, str) else None
    if parsed is None or parsed[0] >= 60:
        raise ValueError("invalid live jump-ball clock")
    return parsed[1]


@dataclass(frozen=True)
class V3TeamJumpRecovery:
    opposing_jumper: int
    team_id: int
    source: str
    evidence_sha256: str


class V3JumpBallEvidence:
    """Keep the reviewed join and original live bytes; never repair native rows.

    This bounded contract supports team recoveries only. Provenance labels are
    caller assertions, not authentication of an official capture or review.
    """

    def __init__(self, review_bytes, live_bytes):
        self._review, self._live = _decode(review_bytes), _decode(live_bytes)
        self.review_bytes, self.live_bytes = review_bytes, live_bytes
        self.sha256 = hashlib.sha256(review_bytes).hexdigest()
        self.live_sha256 = hashlib.sha256(live_bytes).hexdigest()

    @classmethod
    def from_files(cls, review_path, live_path):
        return cls(Path(review_path).read_bytes(), Path(live_path).read_bytes())

    @property
    def data(self):
        return json_copy(self._review)

    def bind(self, pbp, context):
        if context.game_id != pbp.game_id or not context.roster_complete:
            raise ValueError(
                "jump-ball evidence requires a complete matching game context"
            )
        review, game = self._review, self._live.get("game")
        if (
            type(review.get("schema_version")) is not int
            or review["schema_version"] != 1
            or review.get("game_id") != pbp.game_id
            or not isinstance(game, dict)
            or game.get("gameId") != pbp.game_id
        ):
            raise ValueError(
                "jump-ball evidence requires schema 1 and matching game IDs"
            )
        if (
            not isinstance(pbp.source_bytes, bytes)
            or review.get("pbp_sha256") != hashlib.sha256(pbp.source_bytes).hexdigest()
        ):
            raise ValueError(
                "jump-ball evidence pbp_sha256 does not match native bytes"
            )
        if review.get("live_sha256") != self.live_sha256:
            raise ValueError("jump-ball evidence live_sha256 does not match live bytes")
        source = review.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("jump-ball evidence requires source provenance")
        actions, records = game.get("actions"), review.get("jumps")
        if not isinstance(actions, list) or any(
            not isinstance(a, dict) for a in actions
        ):
            raise ValueError("live jump-ball actions must be an array of objects")
        if not isinstance(records, list) or not records:
            raise ValueError("jump-ball review requires nonempty jumps")
        result, live_used = {}, set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("jump-ball review record must be an object")
            native_index, live_index = record.get("source_index"), record.get(
                "live_source_index"
            )
            if (
                type(native_index) is not int
                or not 0 <= native_index < len(pbp.items)
                or type(live_index) is not int
                or not 0 <= live_index < len(actions)
                or native_index in result
                or live_index in live_used
            ):
                raise ValueError(
                    "jump-ball review has duplicate or invalid source indices"
                )
            reason = record.get("source")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("each reviewed jump requires source provenance")
            native, live = pbp.items[native_index], actions[live_index]
            opponent, team = self._match(native, live, pbp, context, actions, record)
            result[native_index] = V3TeamJumpRecovery(
                opponent,
                team,
                f"{source}; live row {live_index}; live sha256={self.live_sha256}; {reason}",
                self.sha256,
            )
            live_used.add(live_index)
        return MappingProxyType(result)

    def _match(self, native, live, pbp, context, actions, record):
        if native.action_type != "Jump Ball" or native.description.strip():
            raise ValueError(
                "jump-ball supplementation requires a blank native jump description"
            )
        number = native.action_number
        if (
            type(live.get("actionNumber")) is not int
            or live["actionNumber"] != number
            or sum(a.get("actionNumber") == number for a in actions) != 1
            or sum(r.action_number == number for r in pbp.items) != 1
            or type(live.get("period")) is not int
            or live["period"] != native.period
            or (live.get("actionType"), live.get("subType"))
            != ("jumpball", "recovered")
        ):
            raise ValueError(
                "jump-ball join has ambiguous identity, period or event kind"
            )
        basis = record.get("clock_basis")
        if basis == "exact":
            if (
                live.get("descriptor") != "heldball"
                or _clock(live.get("clock")) != native.seconds_remaining_exact
            ):
                raise ValueError("jump-ball clocks conflict")
        elif basis == "opening_recovery":
            self._opening_clock(native, live, pbp, actions, record)
        else:
            raise ValueError("jump-ball review requires a supported clock_basis")
        won, lost = live.get("jumpBallWonPersonId"), live.get("jumpBallLostPersonId")
        if any(
            type(pid) is not int or context.player(pid) is None for pid in (won, lost)
        ):
            raise ValueError("live jumpers must be explicit roster players")
        if context.player(won).team_id == context.player(lost).team_id:
            raise ValueError("live jumpers must belong to opposing teams")
        actor = native.get("personId")
        if actor not in (won, lost):
            raise ValueError("native jumper conflicts with live jumper identities")
        for pid, field in (
            (won, "jumpBallWonPlayerName"),
            (lost, "jumpBallLostPlayerName"),
        ):
            name = live.get(field)
            if not isinstance(name, str) or pid not in context.candidates(
                name, context.player(pid).team_id
            ):
                raise ValueError(
                    "live jumper name conflicts with roster identity or supported aliases"
                )
        team, tricode = live.get("teamId"), live.get("teamTricode")
        filtered = live.get("personIdsFilter")
        if (
            type(team) is not int
            or team not in context.team_ids
            or type(live.get("possession")) is not int
            or live["possession"] != team
            or type(live.get("personId")) is not int
            or live["personId"] != 0
            or any(
                type(live.get(k, 0)) is not int or live.get(k, 0) != 0
                for k in ("jumpBallRecoverdPersonId", "jumpBallRecoveredPersonId")
            )
            or not isinstance(tricode, str)
            or not tricode.strip()
            or live.get("jumpBallRecoveredName") != f"Team ({tricode})"
            or not isinstance(filtered, list)
            or len(filtered) != 2
            or any(type(pid) is not int for pid in filtered)
            or set(filtered) != {won, lost}
        ):
            raise ValueError("live team recovery evidence is missing or conflicting")
        return lost if actor == won else won, team

    def _opening_clock(self, native, live, pbp, actions, record):
        # Provider recovery time is distinct from the native opening tip time.
        # Only the first live action after Q1 start, bounded by the same next
        # event in both snapshots, qualifies; no general clock tolerance exists.
        opening = pbp.rules.opening_clock(1)
        if (
            native.period != 1
            or native.order != 1
            or record["live_source_index"] != 1
            or native.seconds_remaining_exact != opening
            or live.get("descriptor") != "startperiod"
            or not 0 <= _clock(live.get("clock")) <= opening
            or len(actions) < 3
            or len(pbp.items) < 3
            or (actions[0].get("actionType"), actions[0].get("subType"))
            != ("period", "start")
            or type(actions[0].get("period")) is not int
            or actions[0].get("period") != 1
            or _clock(actions[0].get("clock")) != opening
            or (pbp.items[0].action_type, pbp.items[0].sub_type) != ("period", "start")
            or pbp.items[0].period != 1
            or pbp.items[0].seconds_remaining_exact != opening
            or pbp.items[2].period != 1
            or type(actions[2].get("period")) is not int
            or actions[2].get("period") != 1
            or type(actions[2].get("actionNumber")) is not int
            or actions[2].get("actionNumber") != pbp.items[2].action_number
            or _clock(actions[2].get("clock")) != pbp.items[2].seconds_remaining_exact
            or _clock(actions[2].get("clock")) > _clock(live.get("clock"))
            or any(live.get(k) != "0" for k in ("scoreHome", "scoreAway"))
        ):
            raise ValueError(
                "opening jump recovery clock lacks matching period/next-event boundaries"
            )
        following, observed = pbp.items[2], actions[2]
        if (
            following.action_type not in ("Made Shot", "Missed Shot")
            or observed.get("actionType") != f"{following.get('shotValue')}pt"
            or observed.get("shotResult") != following.get("shotResult")
            or type(observed.get("isFieldGoal")) is not int
            or observed.get("isFieldGoal") != 1
            or any(
                type(observed.get(key)) is not int
                or observed[key] != following.get(key)
                for key in ("personId", "teamId")
            )
        ):
            raise ValueError("opening jump next-event shot identity conflicts")
