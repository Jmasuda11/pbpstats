"""Bounded adaptations of the legacy Stats V2 loader, without editing source rows.

V2 repairs opening markers, applies substitutions in order, derives scores,
and treats replay rows as part of the final snapshot. Identity resolution and
all V3 lineup/possession checks still apply. This is not a replay undo engine.
"""

from collections import Counter

from pbpstats.resources.period_clock import parse_period_clock


def technical_activity(row):
    return (
        row.get("actionType") == "Foul"
        and ("Technical" in row.get("subType", "") or row.get("subType") == "Bench")
        or row.get("actionType") == "Free Throw"
        and row.get("subType", "").startswith("Free Throw Technical")
    )


def period_order(indexed_rows, rules):
    """Return source indices in processing order and explicit repair diagnostics.

    Like V2's _fix_order_when_technical_foul_before_period_start, move the
    marker ahead of opening-clock technical activity. Also handle an opening
    OT jump and a zero-clock team-heave/rebound pair after a closing marker.
    Never sort a whole stream or supply missing markers, clocks or identities.
    Unrecognized sequences are unchanged so normal validation rejects them.
    """
    rows = list(indexed_rows)
    result, notes = [], []
    position = 0
    while position < len(rows):
        period = rows[position][1]["period"]
        stop = position + 1
        while stop < len(rows) and rows[stop][1]["period"] == period:
            stop += 1
        segment = rows[position:stop]
        starts = [i for i, (_, r) in enumerate(segment)
                  if (r["actionType"], r["subType"]) == ("period", "start")]
        if len(starts) == 1 and starts[0] > 0:
            n = starts[0]
            before = segment[:n]
            clocks = [parse_period_clock(r["clock"]) for _, r in segment[:n + 1]]
            allowed = all(
                technical_activity(r)
                or r["actionType"] == "Rebound" and i > 0
                and before[i - 1][1]["actionType"] == "Free Throw"
                and technical_activity(before[i - 1][1])
                or period > 4 and n == 1 and r["actionType"] == "Jump Ball"
                for i, (_, r) in enumerate(before)
            )
            if allowed and all(c and c[1] == rules.opening_clock(period) for c in clocks):
                affected = tuple(i for i, _ in segment[:n + 1])
                segment = [segment[n]] + before + segment[n + 1:]
                notes.append(dict(stage="ordering", code="period_start_reordered",
                                  message="Opening marker processed before same-clock technical activity or OT jump; source order retained.",
                                  source_indices=affected))
        ends = [i for i, (_, r) in enumerate(segment)
                if (r["actionType"], r["subType"]) == ("period", "end")]
        if len(ends) == 1:
            n = ends[0]
            tail = segment[n + 1:]
            if (len(tail) == 2 and tail[0][1]["actionType"] == "Heave"
                    and tail[0][1]["subType"] == "Team Field Goal Attempt"
                    and tail[1][1]["actionType"] == "Rebound"
                    and rules.team_heave(period, 0)
                    and all((c := parse_period_clock(r["clock"])) and c[1] == 0
                            for _, r in segment[n:])):
                affected = tuple(i for i, _ in segment[n:])
                segment = segment[:n] + tail + [segment[n]]
                notes.append(dict(stage="ordering", code="period_end_reordered",
                                  message="Zero-clock closing marker processed after team heave and rebound; source order retained.",
                                  source_indices=affected))
        result.extend(i for i, _ in segment)
        position = stop
    return tuple(result), notes


def reconcile_scoring(box, events):
    """Require event-derived team AND individual points to match the box score."""
    teams, players = Counter(), Counter()
    for event in events:
        if event.facts.recorded_points:
            teams[event.team_id] += event.facts.recorded_points
            players[event.player1_id] += event.facts.recorded_points
    def check(actual, expected, label):
        if type(expected) is not int or expected < 0 or actual != expected:
            raise ValueError(f"V2-derived scoring conflicts with box score for {label}: {actual} versus {expected!r}")
    for side in ("homeTeam", "awayTeam"):
        team = box.source_data["boxScoreTraditional"][side]
        check(teams[team["teamId"]], team.get("statistics", {}).get("points"), f"team {team['teamId']}")
        for player in team["players"]:
            expected = player.get("statistics", {}).get("points")
            # Some official zero-minute/DNP rows have no statistics. Require
            # published zero-minute evidence, not merely absence of events.
            if expected is None:
                from pbpstats.data_loader.stats_nba_v3.preparation import _published_seconds
                if _published_seconds(player) == 0:
                    expected = 0
            check(players[player["personId"]], expected, f"player {player['personId']}")
