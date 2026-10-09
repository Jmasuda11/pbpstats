"""Recorded legacy override files, bound to the exact V3 play-by-play bytes."""

from dataclasses import dataclass
import hashlib
import json

from pbpstats.overrides import IntDecoder

from .decoder import CLOCK, V3DecodeError


BAD_POSSESSIONS = "bad_pbp_possessions.json"
CHANGE_EVENTS = "possession_change_event_overrides.json"
KEEP_EVENTS = "non_possession_changing_event_overrides.json"
STARTERS = "missing_period_starters.json"
# The original has no files for these: for a recorded event that is out of
# order, mislabeled, duplicated or incomplete, its remedy is to edit the
# play-by-play file. Each entry is that edit. An event-order entry, [event,
# before], moves one event to just before another event at the same period and
# clock. A subtype entry, {event: label}, gives the V3 subtype the event should
# have recorded. A clock entry, {event: V3 clock}, changes only the tenths
# within the recorded second. A duplicate entry, {event: kept}, drops an event
# recorded twice, keeping its identical copy. A block entry, {event: person},
# names the blocker of a missed shot that V3 records without its block. A
# location entry, {event: "h" or "v"}, gives the side of a team heave that V3
# records without one. A live-number entry, {event: live action}, names the
# live play-by-play action of a jump ball that V3 renumbered. A tip-recipient
# entry, {event: person}, names the player who secured a jump ball that V3
# credits to someone else.
EVENT_ORDER = "event_order.json"
EVENT_SUBTYPES = "event_subtypes.json"
EVENT_CLOCKS = "event_clocks.json"
EVENT_DUPLICATES = "event_duplicates.json"
EVENT_BLOCKS = "event_blocks.json"
EVENT_LOCATIONS = "event_locations.json"
EVENT_LIVE_NUMBERS = "event_live_numbers.json"
EVENT_TIP_RECIPIENTS = "event_tip_recipients.json"
SUPPORTED = {
    BAD_POSSESSIONS,
    CHANGE_EVENTS,
    EVENT_BLOCKS,
    EVENT_CLOCKS,
    EVENT_DUPLICATES,
    EVENT_LIVE_NUMBERS,
    EVENT_LOCATIONS,
    EVENT_ORDER,
    EVENT_SUBTYPES,
    EVENT_TIP_RECIPIENTS,
    KEEP_EVENTS,
    STARTERS,
}
# Entries that map an event to a number: a kept event, a blocker, a live action
# or a tip recipient.
NUMBERED = {
    EVENT_BLOCKS: "block",
    EVENT_DUPLICATES: "duplicate",
    EVENT_LIVE_NUMBERS: "live-number",
    EVENT_TIP_RECIPIENTS: "tip-recipient",
}


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
                if name == EVENT_ORDER:
                    if not isinstance(entries, list) or any(
                        not isinstance(move, list)
                        or len(move) != 2
                        or any(type(n) is not int or n < 0 for n in move)
                        or move[0] == move[1]
                        for move in entries
                    ):
                        raise V3DecodeError("Invalid event-order override move")
                    continue
                if name in (EVENT_SUBTYPES, EVENT_CLOCKS):
                    if not isinstance(entries, dict) or not entries or any(
                        type(event) is not int
                        or event < 0
                        or not isinstance(value, str)
                        or not value.strip()
                        or name == EVENT_CLOCKS and not CLOCK.fullmatch(value)
                        for event, value in entries.items()
                    ):
                        raise V3DecodeError("Invalid event {} override".format(
                            "subtype" if name == EVENT_SUBTYPES else "clock"))
                    continue
                if name == EVENT_LOCATIONS:
                    if not isinstance(entries, dict) or not entries or any(
                        type(event) is not int or event < 0 or value not in ("h", "v")
                        for event, value in entries.items()
                    ):
                        raise V3DecodeError("Invalid event location override")
                    continue
                if name in NUMBERED:
                    if not isinstance(entries, dict) or not entries or any(
                        type(event) is not int
                        or event < 0
                        or type(value) is not int
                        or value <= 0
                        or value == event
                        for event, value in entries.items()
                    ):
                        raise V3DecodeError("Invalid event {} override".format(NUMBERED[name]))
                    continue
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
