"""A validated raw action; basketball interpretation belongs to enhanced events."""

from pbpstats.resources.json_copy import json_copy
from pbpstats.resources.period_clock import parse_period_clock, period_length_seconds


class StatsNbaV3PbpItem:
    """Preserve a V3 action and its zero-based source position, ``order``.

    Source fields retain their original spelling and values in ``data``.
    Read-only properties expose the validated identity and clock fields.
    No arbitrary source keys are installed as Python attributes.

    ``data`` copies the whole action on every read. Bind it to a local rather
    than indexing it repeatedly, or read one field with :meth:`get`.

    ``event`` is stored by reference. :class:`StatsNbaV3PbpLoader` passes an
    action out of its own private copy of the payload, so nothing a caller
    holds can reach it; a caller constructing items directly must not mutate
    ``event`` afterwards.
    """

    __slots__ = ("_data", "_order", "_game_id", "_seconds_remaining")

    def __init__(self, event, order, game_id):
        context = f"Stats V3 game {game_id}, game.actions[{order}]"
        if not isinstance(event, dict):
            raise ValueError(f"{context}: action must be an object")
        for field, minimum in (("actionId", 0), ("actionNumber", 0), ("period", 1)):
            value = event.get(field)
            if type(value) is not int or value < minimum:
                raise ValueError(f"{context}.{field}: expected integer >= {minimum}")
        for field in ("actionType", "subType", "description", "clock"):
            if not isinstance(event.get(field), str):
                raise ValueError(f"{context}.{field}: expected a string")
        parsed = parse_period_clock(event["clock"])
        if parsed is None:
            raise ValueError(f"{context}.clock: expected PT<minutes>M<seconds>S")
        seconds, total = parsed
        if seconds >= 60 or total > period_length_seconds(event["period"]):
            raise ValueError(f"{context}.clock: outside NBA period duration")
        self._seconds_remaining = total
        self._game_id = game_id
        self._order = order
        self._data = event

    @property
    def data(self):
        """Return a defensive copy of exactly the recorded action fields.

        This copies the whole action. Use :meth:`get` to read a single field.
        """
        return json_copy(self._data)

    def get(self, field, default=None):
        """Return one recorded field without copying the whole action.

        Scalars are returned as stored; a container is copied so a caller
        cannot reach stored state through it.

        :param str field: source field name, spelled as the feed spells it
        """
        if field not in self._data:
            return default
        value = self._data[field]
        if isinstance(value, (dict, list)):
            return json_copy(value)
        return value

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
    def description(self):
        return self._data["description"]

    @property
    def period(self):
        return self._data["period"]

    @property
    def clock(self):
        return self._data["clock"]

    @property
    def seconds_remaining(self):
        """Return seconds remaining in the period as a ``float``.

        This matches :obj:`~pbpstats.resources.enhanced_pbp.enhanced_pbp_item.EnhancedPbpItem`,
        so V3 items can be mixed with other providers' events in shared
        arithmetic. ``seconds_remaining_exact`` keeps the recorded precision.
        """
        return float(self._seconds_remaining)

    @property
    def seconds_remaining_exact(self):
        """Return the recorded clock as a ``Decimal``, without truncating it.

        Keep this off shared event arithmetic: mixing ``Decimal`` with the
        ``float`` the shared interface uses raises ``TypeError``.
        """
        return self._seconds_remaining
