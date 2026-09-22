"""Recorded cross-league validation and rule-boundary counterexamples, offline."""

import hashlib
import json
import socket
from collections import Counter, defaultdict
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
import test_stats_v3_lineups as synthetic
import test_stats_v3_possessions as plays
from v3_league_fixtures import DATA, classified, lineup_evidence

from pbpstats.data_loader.stats_nba_v3.boxscore import (
    StatsNbaV3BoxscoreFileLoader,
    StatsNbaV3BoxscoreLoader,
)
from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.context import V3BenchPerson
from pbpstats.data_loader.stats_nba_v3.game import load_game
from pbpstats.data_loader.stats_nba_v3.lineups import (
    StatsNbaV3LineupLoader,
    V3LineupEvidence,
    lineup_fingerprints,
)
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData
from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader
from pbpstats.resources.league_rules import V3LeagueRules

MANIFEST = json.loads((DATA / "manifest.json").read_bytes())["games"]
COMPLETE = [
    "0022500341",
    "1022600100",
    "1022600101",
    "2022500001",
    "0042500317",
    "0022500166",
    "0022500340",
    "0022500001",
    "1022600001",
]
EXPECTED = {
    "0022500341": (494, 207, {1610612739: 102, 1610612759: 102}),
    "1022600100": (433, 177, {1611661317: 87, 1611661320: 88}),
    "1022600101": (400, 157, {1611661313: 77, 1611661322: 78}),
    "2022500001": (510, 214, {1612709890: 105, 1612709914: 106}),
    "0042500317": (482, 186, {1610612760: 93, 1610612759: 92}),
    "0022500166": (506, 201, {1610612737: 101, 1610612753: 100}),
    "0022500340": (476, 212, {1610612737: 105, 1610612743: 106}),
    "0022500001": (584, 225, {1610612760: 111, 1610612745: 112}),
    "1022600001": (448, 177, {1611661313: 88, 1611661323: 88}),
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("cross-league validation attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def lineups(events, evidence):
    return StatsNbaV3LineupLoader(
        events, V3LineupEvidence(json.dumps(evidence).encode(), "test evidence")
    )


def recorded(gid):
    kwargs = {}
    if (DATA / gid / "jump-balls.evidence.json").exists():
        kwargs = dict(
            jump_ball_evidence="jump-balls.evidence.json",
            jump_ball_live=f"pbp/live_{gid}.json",
        )
    game = load_game(gid, DATA / gid, snapshot_complete=True, **kwargs)
    return game.boxscore, game.possessions


def facts(rows, gid="0022500001", ctx=None):
    ctx = ctx or replace(synthetic.context(), game_id=gid, league_id=gid[:2])
    source = {
        "game": {
            "gameId": gid,
            "actions": [
                dict(r, actionId=i + 1, actionNumber=i + 1) for i, r in enumerate(rows)
            ],
        }
    }
    raw = StatsNbaV3PbpLoader(
        gid,
        SimpleNamespace(load_data=lambda _: V3PbpSourceData(source)),
        league_id=gid[:2],
    )
    return StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(raw, ctx, snapshot_complete=True)
    )


def load(rows, gid="0022500001", ctx=None, batches=None):
    events = facts(rows, gid, ctx)
    periods = sorted({e.group.primary.period for e in events.items})
    evidence = dict(
        schema_version=1,
        game_id=gid,
        **lineup_fingerprints(events),
        batches=[
            dict(source_indices=indices, source="Synthetic reviewed batch")
            for indices in (batches or [])
        ],
        periods=[synthetic.period_evidence(p) for p in periods],
    )
    return StatsNbaV3PossessionLoader(lineups(events, evidence))


def published_seconds(display):
    return (
        sum(int(v) * scale for v, scale in zip(display.split(":"), (60, 1)))
        if ":" in display
        else 0
    )


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["game_id"])
def test_all_captures_are_final_and_hash_bound(entry):
    gid = entry["game_id"]
    paths = {
        "pbp_sha256": f"pbp/stats_v3_{gid}.json",
        "boxscore_sha256": f"game_details/stats_v3_boxscore_{gid}.json",
        "evidence_sha256": f"game_details/stats_v3_boxscore_{gid}.evidence.json",
        "observation_sha256": "official_game.json",
    }
    for key, path in paths.items():
        assert (
            hashlib.sha256((DATA / gid / path).read_bytes()).hexdigest() == entry[key]
        )
    official = json.loads((DATA / gid / "official_game.json").read_bytes())
    assert official["gameId"] == gid and official["gameStatus"] == 3
    assert official["period"] >= 4
    box = StatsNbaV3BoxscoreLoader(
        gid,
        StatsNbaV3BoxscoreFileLoader(DATA / gid, league_id=gid[:2]),
        league_id=gid[:2],
    )
    assert box.context.league_id == gid[:2]
    assert box.context.team_ids == (official["homeTeamId"], official["awayTeamId"])
    raw = StatsNbaV3PbpLoader(
        gid, StatsNbaV3PbpFileLoader(DATA / gid, league_id=gid[:2])
    )
    assert len(raw.items) == entry["actions"]


def player_totals(result):
    totals = defaultdict(Counter)
    for e in result.events:
        p = totals[e.player1_id]
        p["points"] += e.facts.recorded_points
        if e.facts.kind == "field_goal":
            p["fieldGoalsAttempted"] += 1
            p["fieldGoalsMade"] += bool(e.is_made)
            if e.facts.shot_value == 3:
                p["threePointersAttempted"] += 1
                p["threePointersMade"] += bool(e.is_made)
            if e.is_made and hasattr(e, "player2_id"):
                totals[e.player2_id]["assists"] += 1
            if hasattr(e, "player3_id"):
                totals[e.player3_id]["blocks"] += 1
        elif e.facts.kind == "free_throw":
            # G League box scores count physical attempts, while points can be 1/2/3.
            p["freeThrowsAttempted"] += 1
            p["freeThrowsMade"] += bool(e.is_made)
        elif e.facts.kind == "rebound" and e.is_real_rebound:
            p["reboundsOffensive" if e.oreb else "reboundsDefensive"] += 1
        elif e.facts.kind == "turnover":
            p["turnovers"] += 1
            if e.is_steal:
                totals[e.player3_id]["steals"] += 1
        elif e.facts.kind == "foul":
            p["foulsPersonal"] += bool(e.counts_as_personal_foul)
    return totals


@pytest.mark.parametrize("gid", COMPLETE)
def test_full_games_reconcile_all_player_stats_minutes_and_period_scores(gid):
    box, result = recorded(gid)
    event_count, group_count, counts = EXPECTED[gid]
    assert (len(result.events), len(result.items), result.counts_by_team) == (
        event_count,
        group_count,
        counts,
    )
    assert [e.facts for p in result.items for e in p.events] == [
        i.event for i in result.lineups.items
    ]
    totals = player_totals(result)
    seconds = defaultdict(Decimal)
    for stat in result.base_stats:
        if stat["stat_key"] in ("SecondsPlayedOff", "SecondsPlayedDef"):
            seconds[int(stat["player_id"])] += stat["stat_value"]
    official = json.loads((DATA / gid / "official_game.json").read_bytes())
    for side in ["homeTeam", "awayTeam"]:
        team = box.source_data["boxScoreTraditional"][side]
        for player in team["players"]:
            pid = player["personId"]
            stats = player["statistics"]
            assert abs(
                seconds[pid] - published_seconds(stats.get("minutes", ""))
            ) <= Decimal(".5"), pid
            for key in [
                "points",
                "fieldGoalsAttempted",
                "fieldGoalsMade",
                "threePointersAttempted",
                "threePointersMade",
                "freeThrowsAttempted",
                "freeThrowsMade",
                "assists",
                "blocks",
                "steals",
                "turnovers",
                "reboundsOffensive",
                "reboundsDefensive",
                "foulsPersonal",
            ]:
                assert totals[pid][key] == stats.get(key, 0), (pid, key)
        assert result.events[-1].score[team["teamId"]] == official[side]["score"]
        cumulative = 0
        for period in official[side]["periods"]:
            cumulative += period["score"]
            end = next(
                e
                for e in result.events
                if e.period == period["period"] and e.facts.kind == "period_end"
            )
            assert end.score[team["teamId"]] == cumulative
    if gid == "2022500001":
        assert result.overtime_target == 119
        assert result.events[-1].clock == "96:27"
        assert not result.events[-1].count_as_possession
        assert (
            sum(seconds.values()) == 30330
        )  # (48 minutes + 153-second counter delta) * 10 players


@pytest.mark.parametrize("gid", COMPLETE + ["0022500165"])
def test_starters_have_separate_witnesses_and_q1_matches_box_positions(gid):
    box, result = recorded(gid) if gid != "0022500165" else (None, None)
    if result is None:
        box, events = classified(gid)
    else:
        events = SimpleNamespace(items=[item.event for item in result.lineups.items])
    evidence = lineup_evidence(gid)
    by_index = {e.group.primary.order: e for e in events.items}
    for side in ["home", "away"]:
        marked = sorted(
            p["personId"]
            for p in box.source_data["boxScoreTraditional"][side + "Team"]["players"]
            if p.get("position")
        )
        assert evidence["periods"][0][side] == marked
    for period in evidence["periods"]:
        for pid in period["home"] + period["away"]:
            if gid == "0022500001" and period["period"] == 5 and pid == 1628392:
                assert period["external_witnesses"]
                continue
            if gid == "2022500001" and period["period"] == 5 and pid == 1631342:
                assert period["minute_residuals"][str(pid)] == "153.00"
                continue
            witnesses = period["witnesses"]
            witness = (
                next(w for w in witnesses if w["player_id"] == pid)
                if isinstance(witnesses, list)
                else witnesses[str(pid)]
            )
            event = by_index[witness["source_index"]]
            assert event.group.primary.period == period["period"]
            assert event.participants.require_player(witness["role"]) == pid
            assert not any(
                e.kind == "substitution"
                and e.group.primary.period == period["period"]
                and e.group.primary.order < witness["source_index"]
                and e.participants.require_player("incoming") == pid
                for e in events.items
            )


def test_gleague_fifth_ot_starter_is_uniquely_supported_by_published_minutes():
    box, result = recorded("2022500001")
    seconds = defaultdict(Decimal)
    for e in result.events:
        if e.period <= 4:
            for players in e.lineup.before.values():
                for pid in players:
                    seconds[pid] += e.seconds_since_previous_event
    away = box.source_data["boxScoreTraditional"]["awayTeam"]
    residuals = {
        p["personId"]: Decimal(published_seconds(p["statistics"]["minutes"]))
        - seconds[p["personId"]]
        for p in away["players"]
    }
    on_court = sorted(pid for pid, duration in residuals.items() if duration > 1)
    assert on_court == lineup_evidence("2022500001")["periods"][4]["away"]
    assert len(on_court) == 5
    assert all(abs(residuals[p] - 153) <= Decimal(".5") for p in on_court)
    assert all(
        abs(s) <= Decimal(".5") for p, s in residuals.items() if p not in on_court
    )
    assert not any(
        e.period == 5 and e.facts.kind == "substitution" and e.team_id == away["teamId"]
        for e in result.events
    )


@pytest.mark.parametrize(
    "gid,index", [("1022600001", 34), ("0022500340", 1), ("0022500001", 292)]
)
def test_blank_jump_descriptions_remain_missing_evidence(gid, index):
    _, events = classified(gid)
    jump = next(e for e in events.items if e.group.primary.order == index)
    with pytest.raises(ValueError, match="opposing_jumper is unresolved"):
        jump.participants.require_player("opposing_jumper")


@pytest.mark.parametrize(
    "gid,pid",
    [("0042500317", 1627327), ("1022600061", 1642754), ("0022500166", 202427)],
)
def test_unsourced_bench_id_does_not_enter_the_player_roster(gid, pid):
    box, _ = classified(gid)
    raw = StatsNbaV3PbpLoader(gid, StatsNbaV3PbpFileLoader(DATA / gid))
    with pytest.raises(ValueError, match=f"{pid} is outside the complete roster"):
        StatsNbaV3ParticipantLoader(
            raw, replace(box.context, bench_people=()), snapshot_complete=True
        )


def test_conflicting_jump_turnover_control_does_not_get_a_restart_override():
    _, events = classified("0022500165")
    with pytest.raises(ValueError, match=r"\(26, 27\).*additional restart evidence"):
        StatsNbaV3PossessionLoader(lineups(events, lineup_evidence("0022500165")))


@pytest.mark.parametrize(
    "league,gid,seconds",
    [("00", "0022500341", 720), ("10", "1022600101", 600), ("20", "2022500001", 720)],
)
def test_league_selection_controls_clock_and_rejects_mismatch_before_io(
    league, gid, seconds
):
    rules = V3LeagueRules.for_game(gid, league)
    assert rules.regulation_seconds == seconds
    wrong = "10" if league != "10" else "00"
    source = SimpleNamespace(load_data=lambda _: pytest.fail("mismatch reached source"))
    for loader in (StatsNbaV3PbpLoader, StatsNbaV3BoxscoreLoader):
        with pytest.raises(ValueError, match="conflicts with game_id"):
            loader(gid, source, league_id=wrong)
    for loader in (StatsNbaV3PbpFileLoader, StatsNbaV3BoxscoreFileLoader):
        with pytest.raises(ValueError, match="conflicts with game_id"):
            loader(DATA / "missing", league_id=wrong).load_data(gid)


@pytest.mark.parametrize("league", ["30", 0, [], True])
def test_invalid_league_parameter_is_explicit(league):
    with pytest.raises(ValueError, match="league_id"):
        V3LeagueRules.for_game("0022500341", league)


def test_wnba_clocks_and_unsupported_formats():
    with pytest.raises(ValueError, match="period duration"):
        facts([synthetic.start()], "1022600001")
    assert V3LeagueRules.for_game("1022600001").opening_clock(5) == 300
    assert V3LeagueRules.for_game("2022100001").opening_clock(5) == 300
    assert V3LeagueRules.for_game("2022200001").opening_clock(5) == 5940
    with pytest.raises(ValueError, match="four-quarter"):
        V3LeagueRules.for_game("1020500001")
    with pytest.raises(ValueError, match="regular-season and playoff"):
        V3LeagueRules.for_game("2052500001")
    with pytest.raises(ValueError, match="season_start_year"):
        V3LeagueRules("00", True)


@pytest.mark.parametrize("value", [1, 2, 3])
def test_gleague_single_shot_value_and_physical_attempts(value):
    subtype = f"Free Throw {value}PT"
    ft = synthetic.row(
        "Free Throw",
        subtype,
        "PT10M00S",
        1,
        plays.HOME,
        f"Player1 {subtype} ({value} PTS)",
    )
    preceding = [synthetic.shot(1, "PT10M00S")] if value == 1 else []
    result = load(
        [synthetic.start()] + preceding + [plays.foul(), ft, synthetic.end()],
        "2022500001",
    )
    event = result.events[-2]
    assert event.facts.recorded_points == value
    assert getattr(event, f"is_ft_{value}pt")
    assert event.trip_foul.number_of_fta_for_foul == value
    assert event.is_end_ft
    assert player_totals(result)[1]["freeThrowsAttempted"] == 1


@pytest.mark.parametrize(
    "gid,period,clock",
    [
        ("0022500001", 1, "PT10M00S"),
        ("1022600001", 1, "PT09M00S"),
        ("2021800001", 1, "PT10M00S"),
        ("2022500001", 4, "PT02M00S"),
        ("2022500001", 5, "PT99M00S"),
    ],
)
def test_single_shot_free_throws_fail_outside_gleague_phase(gid, period, clock):
    row = synthetic.row(
        "Free Throw",
        "Free Throw 2PT",
        clock,
        1,
        plays.HOME,
        "Player1 Free Throw 2PT (2 PTS)",
        period,
    )
    with pytest.raises(ValueError, match="single-shot free throw"):
        facts([row], gid)


def test_gleague_multi_attempt_trip_only_at_regulation_end_or_overtime():
    with pytest.raises(ValueError, match="multi-attempt trip"):
        facts([plays.ft()], "2022500001")
    assert (
        facts([dict(plays.ft(clock="PT02M00S"), period=4)], "2022500001")
        .items[0]
        .free_throw.total
        == 2
    )
    rules = V3LeagueRules.for_game("2022500001")
    assert rules.single_free_throw(4, Decimal("120.001"))
    assert not rules.last_two_minutes(5, Decimal("110"))
    assert rules.last_two_minutes(4, Decimal("110"))


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: d.pop("resolved_replays"), "separate resolution"),
        (lambda d: d["resolved_replays"].append(d["resolved_replays"][0]), "duplicate"),
        (lambda d: d["resolved_replays"][0].update(source=""), "source provenance"),
        (
            lambda d: d["resolved_replays"][0].update(resolution="ignore"),
            "already-applied",
        ),
        (
            lambda d: d["resolved_replays"][0].update(affected_source_indices=[99999]),
            "affected source",
        ),
    ],
)
def test_replay_labels_alone_do_not_prove_corrected_snapshot(mutate, match):
    _, events = classified("1022600100")
    data = lineup_evidence("1022600100")
    mutate(data)
    with pytest.raises(ValueError, match=match):
        StatsNbaV3PossessionLoader(lineups(events, data))


def target_rows():
    rows = []
    for p in range(1, 5):
        rows += [
            synthetic.start(p),
            synthetic.shot(1, period=p),
            synthetic.shot(11, "PT08M00S", team=plays.AWAY, period=p),
            synthetic.end(p),
        ]
    rows.append(dict(synthetic.start(5), clock="PT99M00S"))
    for minute, pid, team, value in [
        (98, 1, plays.HOME, 2),
        (97, 11, plays.AWAY, 2),
        (96, 1, plays.HOME, 2),
        (95, 11, plays.AWAY, 2),
        (94, 1, plays.HOME, 3),
    ]:
        row = synthetic.shot(pid, f"PT{minute}M00S", team=team, period=5)
        if value == 3:
            row.update(shotValue=3, description=f"Player{pid} 3PT Jump Shot (3 PTS)")
        rows.append(row)
    rows.append(dict(synthetic.end(5), clock="PT94M00S"))
    return rows


def test_target_score_requires_tie_target_and_immediate_end():
    rows = target_rows()
    result = load(rows, "2022500001")
    assert result.overtime_target == 15
    assert not result.events[-1].count_as_possession
    early = rows[:-2] + [dict(rows[-1], clock="PT95M00S")]
    with pytest.raises(ValueError, match="before the target"):
        load(early, "2022500001")
    with pytest.raises(ValueError, match="immediately"):
        load(rows[:-1] + [dict(rows[-1], clock="PT93M00S")], "2022500001")
    unequal = rows[:]
    unequal[1] = dict(rows[1], shotValue=3, description="Player1 3PT Jump Shot (3 PTS)")
    with pytest.raises(ValueError, match="tied regulation"):
        load(unequal, "2022500001")


def test_retained_ball_take_foul_is_not_an_and_one_or_ordinary_bonus():
    for subtype, flag in [
        ("Transition Take", "is_transition_take_foul_ft"),
        ("Away From Play", "is_away_from_play_ft"),
    ]:
        result = load(
            [
                synthetic.start(),
                plays.foul(subtype),
                plays.ft(total=1),
                synthetic.shot(2),
                synthetic.end(),
            ]
        )
        assert getattr(result.events[2], flag)
        assert not result.events[2].is_end_ft
        assert result.items[0].events[-1] is result.events[3]


def test_recorded_coach_foul_never_creates_player_or_starter():
    box, result = recorded("0022500341")
    event = next(e for e in result.events if e.facts.group.primary.order == 172)
    assert box.context.player(201690) is None
    assert event.player1_id == 0 and event.team_id == box.context.home_team_id
    assert not event.counts_as_personal_foul
    assert all(
        201690 not in players
        for item in result.lineups.items
        for players in item.after.values()
    )
    with pytest.raises(ValueError, match="bench identity conflicts"):
        replace(
            box.context,
            bench_people=(
                V3BenchPerson(
                    box.context.players[0].player_id,
                    box.context.home_team_id,
                    "Coach",
                    "test",
                ),
            ),
        )
    coach = V3BenchPerson(
        99, plays.HOME, "Coach Name", "Synthetic sourced bench identity"
    )
    ctx = replace(
        synthetic.context(), game_id="0022500001", league_id="00", bench_people=(coach,)
    )
    with pytest.raises(ValueError, match="only supported on a technical"):
        facts([synthetic.shot(99)], ctx=ctx)
    with pytest.raises(ValueError, match="description conflicts"):
        facts(
            [
                synthetic.row(
                    "Foul",
                    "Technical",
                    "PT10M00S",
                    99,
                    plays.HOME,
                    "Someone Else Foul:T.FOUL",
                )
            ],
            ctx=ctx,
        )


def test_team_heave_preserves_team_miss_without_fabricated_player_value():
    heave = synthetic.row(
        "Heave", "Team Field Goal Attempt", "PT00M01S", 0, plays.HOME, "Team Heave"
    )
    rebound = plays.rebound("PT00M01S", pid=0, team=plays.HOME)
    rows = [synthetic.start(), heave, rebound, synthetic.end()]
    result = load(rows)
    event = result.events[1]
    assert event.player1_id == 0 and event.shot_value is None and not event.is_made
    assert result.events[2].is_placeholder
    with pytest.raises(ValueError, match="team heave conflicts"):
        load(rows, "0022400001")


@pytest.mark.parametrize("league", ["00", "10", "20"])
def test_transition_take_clock_exclusions_follow_league(league):
    rules = V3LeagueRules(league, 2026)
    assert rules.transition_take(3, 90)
    assert rules.transition_take(4, Decimal("120.001"))
    assert not rules.transition_take(4, 120)
    assert not rules.transition_take(5, 120)
    assert rules.transition_take(5, 180) == (league != "20")


def test_invalid_transition_take_rejected_before_possession_output():
    rows = target_rows()[:15]
    rows += [
        dict(plays.foul("Transition Take", "PT01M00S"), period=4),
        dict(plays.ft(total=1, clock="PT01M00S"), period=4),
        synthetic.end(4),
    ]
    with pytest.raises(ValueError, match="transition take foul conflicts"):
        load(rows)


def test_gleague_cannot_silently_use_multiple_flagrant_attempts_in_regulation():
    with pytest.raises(ValueError, match="multi-attempt trip"):
        facts([plays.ft(category="Flagrant")], "2022500001")


def test_target_overtime_does_not_allow_a_second_period():
    rows = target_rows() + [synthetic.start(6), synthetic.end(6)]
    with pytest.raises(ValueError, match="exactly one period"):
        load(rows, "2022500001")


@pytest.mark.parametrize("subtype", ["Transition Take", "Away From Play"])
def test_retained_ball_shooter_must_be_on_court_at_the_foul(subtype):
    rows = [
        synthetic.start(),
        plays.foul(subtype),
        synthetic.sub(1, 6),
        plays.ft(total=1, pid=6),
        synthetic.shot(2),
        synthetic.end(),
    ]
    with pytest.raises(ValueError, match="shooter was not on court at the foul"):
        load(rows, batches=[[2]])


@pytest.mark.parametrize("subtype", ["Transition Take", "Away From Play"])
def test_retained_ball_shooter_can_differ_from_fouled_player(subtype):
    result = load(
        [
            synthetic.start(),
            plays.foul(subtype, foulDrawnPersonId=2),
            synthetic.sub(2, 6),
            plays.ft(total=1),
            synthetic.shot(6),
            synthetic.end(),
        ],
        batches=[[2]],
    )
    assert result.events[3].player1_id == 1
    assert not result.events[3].is_end_ft


def test_wnba_three_point_zones_need_separate_validation():
    start = dict(synthetic.start(), clock="PT10M00S")
    shot = dict(
        synthetic.shot(1, "PT09M00S"),
        shotValue=3,
        description="Player1 3PT Jump Shot (3 PTS)",
        xLegacy=230,
        yLegacy=50,
    )
    result = load(
        [start, shot, synthetic.shot(11, "PT08M00S", team=plays.AWAY), synthetic.end()],
        "1022600001",
    )
    assert result.events[1].shot_value == 3
    with pytest.raises(ValueError, match="WNBA three-point zone"):
        result.events[1].is_corner_3
    with pytest.raises(ValueError, match="WNBA three-point zone"):
        result.items[1].possession_start_type
