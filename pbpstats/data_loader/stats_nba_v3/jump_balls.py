"""Recorded live play-by-play for the jump-ball facts the V3 stats feed omits."""

from dataclasses import dataclass
import hashlib
import json

from .decoder import V3DecodeError


@dataclass(frozen=True)
class V3JumpBallEvidence:
    """One recorded live play-by-play response, reviewed for this V3 input.

    V3 leaves a team-won jump ball's description blank and names a tip
    recipient by surname only. The league's live feed records the same actions
    under the same numbers, with both jumpers' IDs and the recovering player's
    or, for a team recovery, the team in possession. The decoder reads only
    those facts, only for a jump ball V3 leaves undecided; this object performs
    no I/O.
    """

    source_bytes: bytes
    source: str
    pbp_sha256: str

    def decode(self, source_bytes, game_id):
        """Live jump-ball actions by action number, and the input diagnostic."""
        if not isinstance(self.source, str) or not self.source.strip():
            raise V3DecodeError("Jump-ball evidence requires source provenance")
        if hashlib.sha256(source_bytes).hexdigest() != self.pbp_sha256:
            raise V3DecodeError("Jump-ball evidence does not match the raw PBP hash")
        if not isinstance(self.source_bytes, bytes):
            raise V3DecodeError("Jump-ball evidence must be recorded JSON bytes")
        try:
            game = json.loads(self.source_bytes)["game"]
            identity, actions = game["gameId"], list(game["actions"])
        except (ValueError, KeyError, TypeError) as error:
            raise V3DecodeError("Invalid recorded live play-by-play") from error
        if identity != game_id:
            raise V3DecodeError("Jump-ball evidence game identity disagrees")
        jump_balls = {}
        for action in actions:
            if isinstance(action, dict) and action.get("actionType") == "jumpball":
                jump_balls.setdefault(action.get("actionNumber"), []).append(action)
        return jump_balls, dict(
            code="recorded_live_input",
            source=self.source,
            sha256=hashlib.sha256(self.source_bytes).hexdigest(),
            pbp_sha256=self.pbp_sha256,
        )
