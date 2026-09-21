import json
import socket
from collections import Counter, defaultdict
from decimal import Decimal, localcontext

import pytest
import test_stats_v3_lineups as synthetic
from v3_context_fixture import DATA, recorded_boxscore

from pbpstats.data_loader.stats_nba.possessions.file import StatsNbaPossessionFileLoader
from pbpstats.data_loader.stats_nba.possessions.loader import StatsNbaPossessionLoader
from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.lineups import (
    StatsNbaV3LineupLoader,
    V3LineupEvidence,
)
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader
from pbpstats.resources.possessions.possessions import Possessions

HOME, AWAY = synthetic.HOME, synthetic.AWAY
start, end, shot, row, sub = (
    synthetic.start,
    synthetic.end,
    synthetic.shot,
    synthetic.row,
    synthetic.sub,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("possession loading attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def recorded():
    ctx = recorded_boxscore().context
    raw = StatsNbaV3PbpLoader(ctx.game_id, StatsNbaV3PbpFileLoader(DATA))
    facts = StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(raw, ctx, snapshot_complete=True)
    )
    lineups = StatsNbaV3LineupLoader(
        facts, V3LineupEvidence.from_file(DATA / "v3/lineups_0021900001.evidence.json")
    )
    return StatsNbaV3PossessionLoader(lineups)


def load(rows, batches=None, periods=None):
    facts = synthetic.events(rows)
    lineups = synthetic.load(
        facts, synthetic.evidence(facts, batches=batches, periods=periods)
    )
    return StatsNbaV3PossessionLoader(lineups)


def foul(subtype="Shooting", clock="PT10M00S", **extra):
    return row("Foul", subtype, clock, 11, AWAY, "Player11 Foul", **extra)


def ft(attempt=1, total=2, miss=False, category="", pid=1, clock="PT10M00S"):
    subtype = "Free Throw" + (" " + category if category else "")
    if category != "Technical":
        subtype += f" {attempt} of {total}"
    description = (
        ("MISS " if miss else "")
        + f"Player{pid} {subtype}"
        + ("" if miss else " (1 PTS)")
    )
    return row("Free Throw", subtype, clock, pid, HOME, description)


def miss(clock="PT10M00S", pid=1, team=HOME):
    return row(
        "Missed Shot",
        "Jump Shot",
        clock,
        pid,
        team,
        f"MISS Player{pid} Jump Shot",
        isFieldGoal=1,
        shotValue=2,
        shotResult="Missed",
    )


def rebound(clock="PT09M59S", pid=11, team=AWAY):
    return row("Rebound", "Unknown", clock, pid or team, team, "Rebound")


def turnover(clock="PT09M00S", pid=1, team=HOME, subtype="Bad Pass"):
    return row("Turnover", subtype, clock, pid, team, f"Player{pid} Turnover")


def jump(clock="PT09M00S"):
    return row(
        "Jump Ball",
        "",
        clock,
        1,
        HOME,
        "Jump Ball Player1 vs. Player11: Tip to Player12",
    )


def test_recorded_boundaries_match_paired_v2_but_fractional_clocks_change_credit(
    recorded,
):
    old = StatsNbaPossessionLoader(
        recorded.game_id, StatsNbaPossessionFileLoader(str(DATA))
    )
    assert len(recorded.items) == len(old.items) == 227
    assert recorded.counts_by_team == {HOME: 114, AWAY: 112}
    assert Counter(
        p.offense_team_id for p in old.items if p.events[-1].count_as_possession
    ) == {HOME: 112, AWAY: 112}
    differences = []
    for new, previous in zip(recorded.items, old.items):
        assert (
            new.period,
            new.number,
            new.events[-1].event_num,
            new.offense_team_id,
        ) == (
            previous.period,
            previous.number,
            previous.events[-1].event_num,
            previous.offense_team_id,
        )
        assert new.start_score_margin == previous.start_score_margin
        if (
            new.events[-1].count_as_possession
            != previous.events[-1].count_as_possession
        ):
            differences.append((new.period, new.start_time, previous.start_time))
        assert isinstance(new.possession_start_type, str)
    assert differences == [(1, "0:02.8", "0:02"), (3, "0:02.1", "0:02")]
    assert [e.facts for p in recorded.items for e in p.events] == [
        x.event for x in recorded.lineups.items
    ]
    assert recorded.events[-1].score == {HOME: 130, AWAY: 122}


def test_recorded_base_stats_reconcile_player_minutes_and_credited_counts(recorded):
    seconds, counts = defaultdict(Decimal), Counter()
    for stat in recorded.base_stats:
        if stat["stat_key"] in ("SecondsPlayedOff", "SecondsPlayedDef"):
            seconds[stat["player_id"]] += stat["stat_value"]
        if stat["stat_key"] == "OffPoss":
            counts[stat["team_id"]] += stat["stat_value"]
        assert len(stat["lineup_id"].split("-")) == 5
    assert {t: n // 5 for t, n in counts.items()} == recorded.counts_by_team
    page = json.loads((DATA / "v3/nba_page_0021900001.json").read_bytes())
    for side in ("home", "away"):
        assert sum(seconds[p[0]] for p in page[side]["players"]) == 15900
        for pid, name, position, display, points in page[side]["players"]:
            expected = (
                0
                if display.startswith("DNP")
                else sum(
                    int(v) * scale for v, scale in zip(display.split(":"), (60, 1))
                )
            )
            assert abs(seconds[pid] - expected) <= Decimal("0.5"), name


def test_detailed_statistics_fail_instead_of_silently_omitting_foul_drawn(recorded):
    assert any(
        p.status == "unresolved"
        for e in recorded.events
        for role, p in e.facts.participants.participants.items()
        if role == "foul_drawn"
    )
    with pytest.raises(
        ValueError, match="detailed V3 event statistics are unavailable"
    ):
        Possessions(recorded.items).player_stats
    with pytest.raises(ValueError, match="foul-drawn identities are not inferred"):
        recorded.items[0].possession_stats


def test_foul_lineup_gets_ft_possession_credit_after_substitution():
    # Replace a non-shooter between attempts; credit stays with the foul lineup.
    result = load([start(), foul(), ft(), sub(2, 6), ft(2), end()], batches=[[3]])
    final = result.events[4]
    assert 6 in final.current_players[HOME] and 2 not in final.current_players[HOME]
    assert final.event_for_efficiency_stats is result.events[1]
    credits = [s for s in final.base_stats if s["stat_key"] == "OffPoss"]
    assert {s["player_id"] for s in credits} == {1, 2, 3, 4, 5}
    assert not hasattr(result.events[1], "player3_id")


def test_and_one_and_technical_keep_distinct_foul_associations():
    result = load(
        [
            start(),
            shot(1, "PT10M00S"),
            foul(),
            foul("Technical"),
            ft(category="Technical", pid=2),
            ft(total=1),
            end(),
        ]
    )
    made, technical, regular = result.events[1], result.events[4], result.events[5]
    assert made.is_and1 and not made.is_possession_ending_event
    assert not technical.is_end_ft and not technical.is_possession_ending_event
    assert technical.trip_foul is result.events[3]
    assert regular.trip_foul is result.events[2]
    assert regular.is_possession_ending_event
    assert result.events[-1].score[HOME] == 4


@pytest.mark.parametrize(
    "category,foul_type",
    [("Clear Path", "Clear Path"), ("Flagrant", "Flagrant Type 1")],
)
def test_retained_ball_free_throws_and_placeholders_do_not_end_possession(
    category, foul_type
):
    result = load(
        [
            start(),
            miss(),
            rebound("PT09M59S", 1, HOME),
            foul(foul_type, "PT09M00S"),
            ft(category=category, clock="PT09M00S"),
            ft(2, category=category, miss=True, clock="PT09M00S"),
            rebound("PT09M00S", 0, HOME),
            shot(1, "PT08M00S"),
            end(),
        ]
    )
    assert all(not e.is_possession_ending_event for e in result.events[1:7])
    assert result.events[6].placeholder_reason == "non_live_free_throw"
    assert result.counts_by_team == {HOME: 1, AWAY: 1}


def test_offensive_and_defensive_rebounds_and_shot_clock_placeholders():
    result = load(
        [
            start(),
            miss(),
            rebound("PT09M59S", 1, HOME),
            miss("PT09M40S"),
            rebound("PT09M39S", 11, AWAY),
            turnover("PT09M00S", 11, AWAY, "Shot Clock Turnover"),
            rebound("PT09M00S", 0, HOME),
            end(),
        ]
    )
    assert result.events[2].oreb and not result.events[2].is_possession_ending_event
    assert not result.events[4].oreb and result.events[4].is_possession_ending_event
    assert result.events[6].placeholder_reason == "shot_clock_turnover"
    with pytest.raises(ValueError, match="placeholder rebound"):
        result.events[6].oreb


@pytest.mark.parametrize(
    "remaining,credited", [("2", False), ("2.00000000000000001", True)]
)
def test_fractional_credit_threshold_is_preserved(remaining, credited):
    result = load([start(), shot(1, f"PT00M{remaining}S"), end()])
    assert result.items[-1].events[-1].count_as_possession is credited
    assert result.counts_by_team[AWAY] == int(credited)


def test_exact_clocks_and_durations_do_not_depend_on_callers_decimal_context():
    with localcontext() as ctx:
        ctx.prec = 2
        result = load(
            [
                start(),
                shot(1, "PT00M02.80000000000000001S"),
                shot(11, "PT0M2.80000000000000000S", team=AWAY),
                end(),
            ]
        )
        assert result.events[1].clock == "0:02.80000000000000001"
        assert result.events[2].clock == "0:02.8"
        assert result.events[2].seconds_since_previous_event == Decimal(
            "0.00000000000000001"
        )


@pytest.mark.parametrize(
    "rows,match",
    [
        ([start(), ft(), ft(2), end()], "compatible preceding foul"),
        ([start(), foul(), foul(), ft(), ft(2), end()], "compatible preceding foul"),
        ([start(), foul(), ft(2), end()], "attempt 1"),
        ([start(), foul(), ft(), end()], "incomplete free-throw trip"),
        (
            [start(), foul(), ft(), ft(2, clock="PT09M59S"), end()],
            "conflicting free-throw trip",
        ),
        ([start(), foul(), ft(), ft(2, pid=2), end()], "conflicting free-throw trip"),
        (
            [start(), foul(), ft(), shot(1, "PT10M00S"), ft(2), end()],
            "interrupts free-throw trip",
        ),
        ([start(), foul(), ft(total=1), end()], "and-one"),
        ([start(), foul(), shot(1, "PT09M00S"), end()], "missing free-throw trip"),
        ([start(), foul("Personal"), ft(), ft(2), end()], "penalty evidence"),
        (
            [start(), foul(foulDrawnPersonId=2), ft(), ft(2), end()],
            "replacement shooter",
        ),
        ([start(), rebound(), end()], "no unconsumed missed shot"),
        ([start(), miss(), shot(1, "PT09M00S"), end()], "missing rebound evidence"),
        ([start(), miss(), end()], "unresolved missed shot"),
        ([start(), miss(), turnover(), rebound("PT08M59S"), end()], "before turnover"),
        (
            [
                start(),
                turnover(subtype="Shot Clock Turnover"),
                rebound("PT09M00S", 0, HOME),
                rebound("PT09M00S", 0, HOME),
                end(),
            ],
            "reused shot-clock",
        ),
        (
            [
                start(),
                foul("Technical"),
                ft(category="Technical", miss=True),
                rebound("PT09M59S", 0, HOME),
                shot(1, "PT09M00S"),
                end(),
            ],
            "free-throw clock",
        ),
        (
            [
                start(),
                foul(),
                ft(miss=True),
                rebound("PT10M00S", 1, HOME),
                ft(2),
                end(),
            ],
            "non-live rebound",
        ),
        ([start(), shot(1), shot(1, "PT08M00S"), end()], "back-to-back possessions"),
        ([start(), dict(shot(1), scoreHome="9"), end()], "scoreHome conflicts"),
        ([start(), end()], "starting offense"),
        (
            [start(), jump(), shot(11, "PT08M00S", team=AWAY), end()],
            "preceding offense",
        ),
        (
            [start(), foul("Offensive"), shot(11, "PT09M00S", team=AWAY), end()],
            "matching turnover",
        ),
        (
            [start(), row("Violation", "Lane", "PT10M00S", 1, HOME), shot(1), end()],
            "lane ruling",
        ),
        (
            [
                start(),
                row("Violation", "Defensive Goaltending", "PT10M00S", 11, AWAY),
                shot(1),
                end(),
            ],
            "awarded field goal",
        ),
    ],
)
def test_missing_or_conflicting_context_is_rejected(rows, match):
    with pytest.raises(ValueError, match=match):
        load(rows)


def test_interior_jump_ball_uses_validated_recipient_and_shared_boundary_rules():
    result = load(
        [
            start(),
            miss(),
            rebound("PT09M59S", 1, HOME),
            jump(),
            shot(11, "PT08M00S", team=AWAY),
            end(),
        ]
    )
    assert result.events[3].team_id == AWAY
    assert result.events[3].is_possession_ending_event
    assert result.items[0].offense_team_id == HOME
    assert result.items[1].offense_team_id == AWAY


@pytest.mark.parametrize(
    "clocks",
    [
        ["PT11M00S", "PT10M00S", "PT09M00S", "PT08M00S", "PT07M00S"],
        ["PT01M30S", "PT00M30S"],
    ],
)
def test_bonus_free_throws_require_exhausted_fouls_before_the_foul(clocks):
    rows = [start()] + [foul("Personal", clock) for clock in clocks]
    result = load(rows + [ft(clock=clocks[-1]), ft(2, clock=clocks[-1]), end()])
    assert result.events[-2].trip_foul.fouls_to_give_before[AWAY] == 0
    assert result.events[-2].is_penalty_event()
    with pytest.raises(ValueError, match="penalty evidence"):
        load(rows[:-1] + [ft(clock=clocks[-2]), ft(2, clock=clocks[-2]), end()])
    with pytest.raises(ValueError, match="missing free-throw trip"):
        load(rows + [end()])


def test_offensive_foul_and_goaltending_require_matching_recorded_events():
    result = load(
        [
            start(),
            foul("Offensive"),
            turnover("PT10M00S", 11, AWAY, "Offensive Foul Turnover"),
            shot(1),
            row("Violation", "Defensive Goaltending", "PT09M00S", 11, AWAY),
            end(),
        ]
    )
    assert result.items[0].offense_team_id == AWAY
    assert result.events[-1].score == {HOME: 2, AWAY: 0}


def test_defensive_lane_violation_between_made_attempts_does_not_cancel_points():
    result = load(
        [
            start(),
            foul(),
            ft(),
            row("Violation", "Lane", "PT10M00S", 11, AWAY),
            ft(2),
            end(),
        ]
    )
    assert result.events[-1].score == {HOME: 2, AWAY: 0}
    assert result.events[4].is_possession_ending_event


def test_period_links_do_not_cross_regulation_or_overtime_boundaries():
    rows, periods = [], []
    for period in range(1, 6):
        # Exactly one possession per period, including the final overtime.
        rows += [
            start(period),
            dict(miss("PT04M00S"), period=period),
            dict(rebound("PT03M59S", 1, HOME), period=period),
            end(period),
        ]
        periods.append(synthetic.period_evidence(period))
    result = load(rows, periods=periods)
    assert len(result.items) == 5
    for possession in result.items:
        if possession.number == 1:
            assert possession.previous_possession is None
        if possession.next_possession:
            assert possession.next_possession.period == possession.period
    for event in result.events:
        if event.previous_event:
            assert event.previous_event.period == event.period


def test_only_validated_lineups_are_accepted():
    with pytest.raises(TypeError, match="StatsNbaV3LineupLoader"):
        StatsNbaV3PossessionLoader([])
