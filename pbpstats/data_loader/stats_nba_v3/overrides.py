"""Recorded legacy override files, bound to the exact V3 play-by-play bytes."""

from dataclasses import dataclass
import hashlib
import json

from pbpstats.overrides import IntDecoder

from .decoder import V3DecodeError


BAD_POSSESSIONS = "bad_pbp_possessions.json"
CHANGE_EVENTS = "possession_change_event_overrides.json"
KEEP_EVENTS = "non_possession_changing_event_overrides.json"
STARTERS = "missing_period_starters.json"
SUPPORTED = {BAD_POSSESSIONS, CHANGE_EVENTS, KEEP_EVENTS, STARTERS}


@dataclass(frozen=True)
class V3Overrides:
    """Supply original JSON file contents explicitly; never discover local files.

    ``source`` identifies the reviewed correction evidence. ``pbp_sha256`` binds
    that review to one recording. Keys in ``files`` are legacy basenames and
    values are immutable JSON bytes, using the original game/period schema.
    """

    files: dict
    source: str
    pbp_sha256: str

    def decode(self, source_bytes):
        if not isinstance(self.source, str) or not self.source.strip():
            raise V3DecodeError("Overrides require source provenance")
        if hashlib.sha256(source_bytes).hexdigest() != self.pbp_sha256:
            raise V3DecodeError("Overrides do not match the raw PBP hash")
        if not isinstance(self.files, dict) or set(self.files) - SUPPORTED:
            raise V3DecodeError("Unsupported override file")
        decoded, diagnostics = {}, []
        for name, raw in sorted(self.files.items()):
            if not isinstance(raw, bytes):
                raise V3DecodeError("Override files must be recorded JSON bytes")
            try:
                values = json.loads(raw.decode("utf-8"), cls=IntDecoder)
            except (UnicodeError, ValueError) as error:
                raise V3DecodeError("Invalid override JSON: " + name) from error
            if not isinstance(values, dict):
                raise V3DecodeError("Override file must map games: " + name)
            for game, entries in values.items():
                if not isinstance(game, (str, int)) or isinstance(game, bool):
                    raise V3DecodeError("Invalid override game identity")
                if name in (BAD_POSSESSIONS, STARTERS):
                    if not isinstance(entries, dict) or any(
                        type(period) is not int or period < 1 for period in entries
                    ):
                        raise V3DecodeError("Invalid override period map")
                    lists = entries.values()
                    if name == STARTERS:
                        if any(
                            not isinstance(teams, dict)
                            or any(type(team) is not int or team <= 0 for team in teams)
                            for teams in lists
                        ):
                            raise V3DecodeError("Invalid starter override team map")
                        lists = [
                            players
                            for teams in entries.values()
                            for players in teams.values()
                        ]
                else:
                    lists = [entries]
                minimum = 1 if name in (BAD_POSSESSIONS, STARTERS) else 0
                if any(
                    not isinstance(numbers, list)
                    or any(type(n) is not int or n < minimum for n in numbers)
                    for numbers in lists
                ):
                    raise V3DecodeError("Invalid override possession or event number")
            decoded[name] = values
            diagnostics.append(
                dict(
                    code="recorded_override_input",
                    file=name,
                    source=self.source,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    pbp_sha256=self.pbp_sha256,
                )
            )
        return decoded, diagnostics
