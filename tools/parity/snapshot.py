"""Explicit observable contract; no provider object dictionaries as oracles."""

from decimal import Decimal


EVENT_PROPERTIES = (
    "is_made",
    "shot_value",
    "is_assisted",
    "is_blocked",
    "is_technical_ft",
    "is_flagrant_ft",
    "is_end_ft",
    "is_and1",
    "is_make_that_does_not_end_possession",
    "is_real_rebound",
    "oreb",
    "is_no_turnover",
    "is_steal",
    "is_offensive_foul",
    "is_charge",
    "counts_as_personal_foul",
    "counts_towards_penalty",
)
EVENT_RELATIONS = ("foul_that_led_to_ft", "event_for_efficiency_stats", "missed_shot")


def scalar(value):
    if isinstance(value, (float, Decimal)):
        number = Decimal(str(value)).normalize()
        return int(number) if number == number.to_integral_value() else str(number)
    if isinstance(value, dict):
        return {
            str(k): scalar(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))
        }
    if isinstance(value, (tuple, list)):
        return [scalar(v) for v in value]
    return value


def attempt(callback):
    try:
        return scalar(callback())
    except Exception as error:
        # Errors are explicit output, never silently replaced by zero/False.
        return {"unavailable": type(error).__name__, "message": str(error)}


def declared(event, name):
    return name in event.__dict__ or any(
        name in cls.__dict__ for cls in type(event).__mro__
    )


def stats_rows(rows):
    import json

    return sorted(
        (scalar(row) for row in rows), key=lambda row: json.dumps(row, sort_keys=True)
    )


def snapshot(loaded):
    events = []
    for event in loaded.events:
        record = {
            "event_id": event.event_num,
            "period": event.period,
            "seconds": scalar(event.seconds_remaining),
            "participants": {
                name: getattr(event, name, None)
                for name in ("team_id", "player1_id", "player2_id", "player3_id")
            },
            "previous": getattr(event.previous_event, "event_num", None),
            "next": getattr(event.next_event, "event_num", None),
            "lineups": attempt(
                lambda: {k: sorted(v) for k, v in event.current_players.items()}
            ),
            "score": scalar(
                {team: event.score.get(team, 0) for team in event.current_players}
            ),
            "ending": attempt(lambda: event.is_possession_ending_event),
            "counted": attempt(lambda: event.count_as_possession),
            "offense": attempt(event.get_offense_team_id),
            "base_stats": attempt(lambda: stats_rows(event.base_stats)),
            "properties": {
                name: attempt(lambda name=name: getattr(event, name))
                for name in EVENT_PROPERTIES
                if declared(event, name)
            },
            "relations": {
                name: attempt(
                    lambda name=name: getattr(getattr(event, name), "event_num", None)
                )
                for name in EVENT_RELATIONS
                if declared(event, name)
            },
        }
        events.append(record)
    possessions = []
    for possession in loaded.items:
        possessions.append(
            {
                "period": possession.period,
                "number": possession.number,
                "events": [event.event_num for event in possession.events],
                "offense": attempt(lambda: possession.offense_team_id),
                "start_seconds": attempt(
                    lambda: scalar(
                        possession.previous_possession.events[-1].seconds_remaining
                        if possession.previous_possession
                        else possession.events[0].seconds_remaining
                    )
                ),
                "end_seconds": scalar(possession.events[-1].seconds_remaining),
                "start_margin": attempt(lambda: possession.start_score_margin),
                "start_type": attempt(lambda: possession.possession_start_type),
                "previous": getattr(possession.previous_possession, "number", None),
                "next": getattr(possession.next_possession, "number", None),
                "counted": attempt(lambda: possession.events[-1].count_as_possession),
            }
        )
    return {"events": events, "possessions": possessions}


def first_difference(expected, actual, path="$"):
    """Return an actionable first difference, preserving the exact property path."""
    if type(expected) is not type(actual):
        return {"path": path, "expected": expected, "actual": actual}
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                return {
                    "path": path + "." + key,
                    "expected": expected.get(key, {"missing": True}),
                    "actual": actual.get(key, {"missing": True}),
                }
            difference = first_difference(expected[key], actual[key], path + "." + key)
            if difference:
                return difference
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            return {
                "path": path + ".length",
                "expected": len(expected),
                "actual": len(actual),
            }
        for index, (old, new) in enumerate(zip(expected, actual)):
            difference = first_difference(old, new, "{}[{}]".format(path, index))
            if difference:
                return difference
    elif expected != actual:
        return {"path": path, "expected": expected, "actual": actual}
    return None
