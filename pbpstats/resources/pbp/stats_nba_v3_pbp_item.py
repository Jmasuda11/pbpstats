"""A validated raw action; basketball interpretation belongs to enhanced events."""

import re
from copy import deepcopy
from decimal import Decimal, localcontext

CLOCK_PATTERN = re.compile(r"PT([0-9]+)M([0-9]+(?:\.[0-9]+)?)S")


class StatsNbaV3PbpItem:
    """Preserve a V3 action and its zero-based source position, ``order``.

    Source fields retain their original spelling and values in ``data``.
    Read-only properties expose the validated identity and clock fields.
    No arbitrary source keys are installed as Python attributes.
    """

    __slots__ = ("_data", "_order", "_game_id", "_seconds_remaining")

    def __init__(self, event, order, game_id):
        context = f"Stats V3 game {game_id}, game.actions[{order}]"
        if not isinstance(event, dict):
            raise ValueError(f"{context}: action must be an object")
        for field in ("actionId", "actionNumber", "period"):
            value = event.get(field)
            minimum = 1 if field == "period" else 0
            if type(value) is not int or value < minimum:
                raise ValueError(f"{context}.{field}: expected integer >= {minimum}")
        for field in ("actionType", "subType", "description", "clock"):
            if not isinstance(event.get(field), str):
                raise ValueError(f"{context}.{field}: expected a string")
        match = CLOCK_PATTERN.fullmatch(event["clock"])
        if match is None:
            raise ValueError(f"{context}.clock: expected PT<minutes>M<seconds>S")
        minutes, seconds = (Decimal(part) for part in match.groups())
        # Do not let a caller's Decimal context round the source clock.
        with localcontext() as decimal_context:
            decimal_context.prec = max(28, len(event["clock"]) + 3)
            total = minutes * 60 + seconds
        period_seconds = 720 if event["period"] <= 4 else 300
        if seconds >= 60 or total > period_seconds:
            raise ValueError(f"{context}.clock: outside NBA period duration")
        self._seconds_remaining = total
        self._game_id = game_id
        self._order = order
        self._data = deepcopy(event)

    @property
    def data(self):
        """Return a defensive copy of exactly the recorded action fields."""
        return deepcopy(self._data)

    @property
    def game_id(self):
        return self._game_id

    @property
    def order(self):
        return self._order

    @property
    def action_id(self):
        return self._data["actionId"]

    @property
    def action_number(self):
        return self._data["actionNumber"]

    @property
    def action_type(self):
        return self._data["actionType"]

    @property
    def sub_type(self):
        return self._data["subType"]

    @property
    def period(self):
        return self._data["period"]

    @property
    def clock(self):
        return self._data["clock"]

    @property
    def seconds_remaining(self):
        """Return an exact Decimal clock value, without truncating to V2 seconds."""
        return self._seconds_remaining
