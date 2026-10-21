"""Recorded legacy override files, bound to the exact V3 play-by-play bytes."""

from dataclasses import dataclass
import hashlib
import json

from pbpstats.overrides import IntDecoder

from .decoder import CLOCK, V2_JUMP_BALL_FIELDS, V3DecodeError


BAD_POSSESSIONS = "bad_pbp_possessions.json"
CHANGE_EVENTS = "possession_change_event_overrides.json"
KEEP_EVENTS = "non_possession_changing_event_overrides.json"
STARTERS = "missing_period_starters.json"
# The original has no files for these: for a recorded event that is out of
# order, mislabeled, duplicated or incomplete, its remedy is to edit the
# play-by-play file. Each entry is that edit. An event-order entry, [event,
# before], moves one event to just before another event at the same period and
# clock. A subtype entry, {event: label}, gives the V3 subtype the event should
# have recorded. A clock entry, {event: V3 clock}, moves the event at most two
# seconds from its recorded clock. A duplicate entry, {event: kept}, drops an event
# recorded twice, keeping its identical copy. A block entry, {event: person},
# names the blocker of a missed shot that V3 records without its block. A
# location entry, {event: "h" or "v"}, gives the side of a team heave that V3
# records without one. A live-number entry, {event: live action}, names the
# live play-by-play action of a jump ball that V3 renumbered. A tip-recipient
# entry, {event: person or team}, names the player who secured a jump ball that
# V3 credits to someone else, or the team, for a team recovery. A turnover
# entry, {event: {"before": event, "player": person, "subtype": label}}, adds
# under an unused event number a turnover that V3 does not record, just before
# another event and at its period and clock. A clock-reset entry, {event:
# {"clock": V3 clock, "events": [event, ...]}}, records that the game clock was
# set back to a later time right after an event, and moves the events played
# after the reset, which V3 sorts among earlier ones by clock, to follow it.
# A removal entry, {event: kept}, drops an event that another recorded event
# already records, such as a stale substitution left by a later correction,
# keeping its recorded rows with that event. A move entry, {event: after},
# moves an event V3 records at the wrong time to just after another event, at
# that event's period and clock. A team entry, {event: team}, gives the team
# of an event V3 records with neither a team nor a person. A foul-opponent
# entry, {event: person}, names the other party of a double foul whose text
# names nobody. A block-removal entry, [event, ...], drops the block V3 records
# with a missed shot that had none, as V2 records the miss with no blocker; the
# block row stays with the miss. A V2 jump-ball entry, {event: V2 row}, gives
# the V2 export row (the V2_JUMP_BALL_FIELDS of a pinned season archive) of a
# jump ball V3 leaves undecided in a game the live play-by-play does not record.
EVENT_V2_JUMP_BALLS = "event_v2_jump_balls.json"
V2_TEXT_FIELDS = (
    "PCTIMESTRING", "HOMEDESCRIPTION", "NEUTRALDESCRIPTION", "VISITORDESCRIPTION"
)
EVENT_ORDER = "event_order.json"
EVENT_SUBTYPES = "event_subtypes.json"
EVENT_CLOCKS = "event_clocks.json"
EVENT_DUPLICATES = "event_duplicates.json"
EVENT_BLOCKS = "event_blocks.json"
EVENT_LOCATIONS = "event_locations.json"
EVENT_LIVE_NUMBERS = "event_live_numbers.json"
EVENT_TIP_RECIPIENTS = "event_tip_recipients.json"
EVENT_TURNOVERS = "event_turnovers.json"
EVENT_CLOCK_RESETS = "event_clock_resets.json"
EVENT_REMOVALS = "event_removals.json"
EVENT_MOVES = "event_moves.json"
EVENT_TEAMS = "event_teams.json"
EVENT_FOUL_OPPONENTS = "event_foul_opponents.json"
EVENT_BLOCK_REMOVALS = "event_block_removals.json"
SUPPORTED = {
    BAD_POSSESSIONS,
    CHANGE_EVENTS,
    EVENT_BLOCK_REMOVALS,
    EVENT_BLOCKS,
    EVENT_CLOCK_RESETS,
    EVENT_CLOCKS,
    EVENT_DUPLICATES,
    EVENT_FOUL_OPPONENTS,
    EVENT_LIVE_NUMBERS,
    EVENT_LOCATIONS,
    EVENT_MOVES,
    EVENT_ORDER,
    EVENT_REMOVALS,
    EVENT_SUBTYPES,
    EVENT_TEAMS,
    EVENT_TIP_RECIPIENTS,
    EVENT_TURNOVERS,
    EVENT_V2_JUMP_BALLS,
    KEEP_EVENTS,
    STARTERS,
}
# Entries that map an event to a number: a kept event, a blocker, a live action,
# a tip recipient, an event to follow, a team or a foul opponent.
NUMBERED = {
    EVENT_BLOCKS: "block",
    EVENT_DUPLICATES: "duplicate",
    EVENT_FOUL_OPPONENTS: "foul-opponent",
    EVENT_LIVE_NUMBERS: "live-number",
    EVENT_MOVES: "move",
    EVENT_REMOVALS: "removal",
    EVENT_TEAMS: "team",
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
                if name == EVENT_CLOCK_RESETS:
                    if not isinstance(entries, dict) or not entries or any(
                        type(event) is not int
                        or event < 0
                        or not isinstance(value, dict)
                        or set(value) != {"clock", "events"}
                        or not isinstance(value["clock"], str)
                        or not CLOCK.fullmatch(value["clock"])
                        or not isinstance(value["events"], list)
                        or not value["events"]
                        or any(type(n) is not int or n < 0 for n in value["events"])
                        or len(set(value["events"])) != len(value["events"])
                        or event in value["events"]
                        for event, value in entries.items()
                    ):
                        raise V3DecodeError("Invalid event clock-reset override")
                    continue
                if name == EVENT_TURNOVERS:
                    if not isinstance(entries, dict) or not entries or any(
                        type(event) is not int
                        or event < 0
                        or not isinstance(value, dict)
                        or set(value) != {"before", "player", "subtype"}
                        or type(value["before"]) is not int
                        or value["before"] < 0
                        or value["before"] == event
                        or type(value["player"]) is not int
                        or value["player"] <= 0
                        or not isinstance(value["subtype"], str)
                        or not value["subtype"].strip()
                        for event, value in entries.items()
                    ):
                        raise V3DecodeError("Invalid event turnover override")
                    continue
                if name == EVENT_BLOCK_REMOVALS:
                    if not isinstance(entries, list) or not entries or any(
                        type(event) is not int or event < 0 for event in entries
                    ) or len(set(entries)) != len(entries):
                        raise V3DecodeError("Invalid event block-removal override")
                    continue
                if name == EVENT_V2_JUMP_BALLS:
                    # The export's values as read back: numbers for its numeric
                    # fields, text for the clock and the descriptions.
                    if not isinstance(entries, dict) or not entries or any(
                        type(event) is not int
                        or event < 0
                        or not isinstance(row, dict)
                        or set(row) != set(V2_JUMP_BALL_FIELDS)
                        or any(
                            not isinstance(row[field], str)
                            if field in V2_TEXT_FIELDS
                            else type(row[field]) is not int or row[field] < 0
                            for field in row
                        )
                        for event, row in entries.items()
                    ):
                        raise V3DecodeError("Invalid event v2-jump-ball override")
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
