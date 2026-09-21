"""Corroborate the zero-clock live representation of target-score overtime."""

from pbpstats.resources.period_clock import parse_period_clock


def _score(row):
    values = [row.get(key) for key in ("scoreHome", "scoreAway")]
    if any(not isinstance(value, str) or not value.isdecimal() for value in values):
        return None
    return tuple(int(value) for value in values)


def _zero_clock(row):
    clock = row.get("clock")
    parsed = parse_period_clock(clock) if isinstance(clock, str) else None
    return parsed is not None and parsed[1] == 0


def _same_fields(row, expected):
    return all(type(row.get(k)) is type(v) and row[k] == v for k, v in expected.items())


def _is_attempt(row):
    # An unfamiliar flagged field goal is evidence of an unmatched attempt,
    # not a non-scoring row that can be silently skipped.
    return row.get("actionType") in ("2pt", "3pt", "freethrow") or row.get(
        "isFieldGoal"
    ) not in (None, 0)


def _boundaries(native, live, opening_clock):
    markers = [row for row in live if row.get("actionType") == "period"]
    if (
        len(markers) != 2
        or native[0].kind != "period_start"
        or native[-1].kind != "period_end"
        or [e.kind for e in native if e.kind.startswith("period_")]
        != ["period_start", "period_end"]
    ):
        return None
    start, end = markers
    if not _same_fields(
        start, dict(actionNumber=native[0].group.primary.action_number, subType="start")
    ):
        return None
    if not _same_fields(
        end, dict(actionNumber=native[-1].group.primary.action_number, subType="end")
    ):
        return None
    opening = _score(native[0].group.primary.data)
    if opening is None or opening[0] != opening[1] or _score(start) != opening:
        return None
    if _score(end) != _score(native[-1].group.primary.data):
        return None
    clocks = [e.group.primary.seconds_remaining_exact for e in native]
    if clocks[0] != opening_clock or any(a < b for a, b in zip(clocks, clocks[1:])):
        return None
    return start, end, opening


def _attempts_agree(native, live, opening, team_ids):
    """Compare every field goal/free throw in order, including misses and scores."""
    attempts = [e for e in native if e.kind in ("field_goal", "free_throw")]
    rows = [r for r in live if _is_attempt(r)]
    if not attempts or len(attempts) != len(rows):
        return False
    score = dict(zip(team_ids, opening))
    target = opening[0] + 7
    for i, (event, row) in enumerate(zip(attempts, rows)):
        primary = event.group.primary
        expected = dict(
            actionNumber=primary.action_number,
            teamId=event.team_id,
            personId=event.participants.require_player("actor"),
            actionType=f"{event.shot_value}pt"
            if event.kind == "field_goal"
            else "freethrow",
            isFieldGoal=1 if event.kind == "field_goal" else 0,
            shotResult="Made" if event.is_made else "Missed",
        )
        if not _same_fields(row, expected):
            return False
        score[event.team_id] += event.recorded_points
        current = tuple(score[team] for team in team_ids)
        if _score(row) != current:
            return False
        for key, value in zip(("scoreHome", "scoreAway"), current):
            supplied = primary.get(key)
            if supplied not in (None, "") and supplied != str(value):
                return False
        if max(current) >= target and i != len(attempts) - 1:
            return False
    return (
        max(current) >= target
        and _score(native[-1].group.primary.data) == current
        and attempts[-1].group.primary.seconds_remaining_exact
        == native[-1].group.primary.seconds_remaining_exact
    )


def untimed_clock_evidence(event_loader, live_actions):
    """Return corroborated native row indices and an optional rejection reason.

    This joins distinct clock representations; it never changes either source
    or supplies a duration. Only a complete, bounded first target-score overtime
    with matching scoring sequences can replace exact-clock comparison.
    """
    rules = event_loader.context.rules
    native = [e for e in event_loader.items if e.group.primary.period == 5]
    if not rules.untimed(5) or not native:
        return frozenset(), None
    if not event_loader.snapshot_complete:
        return frozenset(), "untimed clock join requires a complete native snapshot"
    if any(e.group.primary.period > 5 for e in event_loader.items) or any(
        type(r.get("period")) is not int or not 1 <= r["period"] <= 5
        for r in live_actions
    ):
        return (
            frozenset(),
            "untimed clock join requires valid periods and only one overtime period",
        )
    live = [r for r in live_actions if r.get("period") == 5]
    if not live or any(
        type(r.get("period")) is not int
        or r.get("periodType") != "OVERTIME"
        or r.get("isTargetScoreLastPeriod") is not True
        or not _zero_clock(r)
        for r in live
    ):
        return (
            frozenset(),
            "untimed live period requires explicit target-score metadata and zero clocks",
        )
    boundaries = _boundaries(native, live, rules.opening_clock(5))
    if boundaries is None:
        return (
            frozenset(),
            "untimed period boundaries, opening scores or native clocks conflict",
        )
    start, end, opening = boundaries
    start_index, end_index = live.index(start), live.index(end)
    if start_index >= end_index or any(
        _is_attempt(r) for r in live[:start_index] + live[end_index + 1 :]
    ):
        return frozenset(), "untimed attempts fall outside period boundaries"
    if not _attempts_agree(
        native,
        live,
        opening,
        (event_loader.context.home_team_id, event_loader.context.away_team_id),
    ):
        return (
            frozenset(),
            "untimed scoring sequence, identities, outcomes or scores conflict",
        )
    return (
        frozenset(e.group.primary.order for e in native if e.kind == "field_goal"),
        None,
    )
