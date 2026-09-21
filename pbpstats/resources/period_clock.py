"""One parser for the ``PT<minutes>M<seconds>S`` period clock.

The Stats V3 feed and the ``live`` provider record the clock in the same
format. Parsing it in one place keeps their results from drifting apart.
"""
import re
from decimal import Context, Decimal, localcontext

CLOCK_PATTERN = re.compile(r"PT([0-9]+)M([0-9]+(?:\.[0-9]+)?)S")

REGULATION_PERIOD_SECONDS = 720
OVERTIME_PERIOD_SECONDS = 300


def parse_period_clock(clock):
    """Return ``(seconds_field, total_seconds)`` as exact ``Decimal`` values.

    ``seconds_field`` is the seconds component exactly as recorded, so a
    caller can reject a value of 60 or more separately from a total that
    overruns the period. Returns ``None`` when ``clock`` does not match
    ``PT<minutes>M<seconds>S``.

    :param str clock: clock as recorded, for example ``PT00M02.80S``
    :rtype: tuple(decimal.Decimal, decimal.Decimal) or None
    """
    match = CLOCK_PATTERN.fullmatch(clock)
    if match is None:
        return None
    minutes, seconds = (Decimal(part) for part in match.groups())
    # A fresh Context inherits nothing from the caller's: not precision, not
    # rounding, not Emax/Emin, not traps. Copying the caller's context would
    # leave all but precision in place and could round or reject the source.
    with localcontext(Context(prec=max(28, len(clock) + 3))):
        return seconds, minutes * 60 + seconds


def period_length_seconds(period):
    """Return the length of ``period`` in seconds.

    :param int period: one-based period number; 5 and up are overtime
    :rtype: int
    """
    return REGULATION_PERIOD_SECONDS if period <= 4 else OVERTIME_PERIOD_SECONDS


def seconds_remaining_from_clock(clock):
    """Return seconds remaining in the period as a ``float``.

    :param str clock: clock as recorded, for example ``PT00M02.80S``
    :raises: ValueError: If clock is not ``PT<minutes>M<seconds>S``
    :rtype: float
    """
    parsed = parse_period_clock(clock)
    if parsed is None:
        raise ValueError(f"expected PT<minutes>M<seconds>S, got {clock!r}")
    return float(parsed[1])
