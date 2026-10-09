"""V2-derived rules retain V3 identity, lineup, source and scoring safeguards."""

import json
import socket
from types import SimpleNamespace

import pytest
import test_stats_v3_lineups as s
import test_stats_v3_possessions as p
import test_stats_v3_preparation as prep
from pbpstats.data_loader.stats_nba_v3.game import load_game
from pbpstats.data_loader.stats_nba_v3.lineups import StatsNbaV3LineupLoader, V3LineupEvidence, lineup_fingerprints
from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader
from pbpstats.data_loader.stats_nba_v3.preparation import _batches
from pbpstats.data_loader.stats_nba_v3.v2_rules import period_order, reconcile_scoring
from pbpstats.resources.league_rules import V3LeagueRules


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("V2 rule adaptation attempted network access")
    monkeypatch.setattr(socket.socket, "connect", fail)


def lineups(rows, enabled=True):
    facts = s.events(rows)
    data = s.evidence(facts)
    diagnostics = []
    data["batches"], pending = _batches(facts, {}, "complete synthetic stream", diagnostics, use_v2_rules=enabled)
    assert not diagnostics and not pending
    evidence = V3LineupEvidence(json.dumps(data).encode(), "test")
    return StatsNbaV3LineupLoader(facts, evidence, use_v2_rules=enabled)


def load(rows, enabled=True):
    return StatsNbaV3PossessionLoader(lineups(rows, enabled))


def test_sequential_substitution_chain_and_reentry_preserve_each_transition():
    result = lineups([s.start(), s.sub(1, 6), s.sub(6, 1), s.shot(1), s.end()])
    assert result.items[1].after[s.HOME] == result.items[2].before[s.HOME] == (2, 3, 4, 5, 6)
    assert result.items[2].after[s.HOME] == (1, 2, 3, 4, 5)
    assert result.items[1].batch_source_indices == (1,)
    assert result.items[2].batch_source_indices == (2,)
    with pytest.raises(ValueError, match="incoming.*on court|already on court"):
        lineups([s.start(), s.sub(1, 6), s.sub(2, 6), s.end()])


def test_technical_before_marker_reorders_processing_not_source_or_fingerprints():
    rows = [p.foul("Technical", clock="PT12M00S"), p.ft(category="Technical", clock="PT12M00S"), s.start(), s.shot(1), s.end()]
    facts = s.events(rows)
    fingerprints = lineup_fingerprints(facts)
    result = load(rows)
    assert [e.facts.group.primary.order for e in result.events] == [2, 0, 1, 3, 4]
    assert result.lineups.diagnostics[0]["source_indices"] == (0, 1, 2)
    assert lineup_fingerprints(facts) == fingerprints
    assert facts.items[0].kind == "foul"
    with pytest.raises(ValueError, match="outside a started period"):
        load(rows, False)
    with pytest.raises(ValueError, match="outside a started period"):
        load([s.shot(1, clock="PT12M00S"), s.start(), s.end()])


def test_ot_jump_and_heave_repairs_are_bounded():
    rules = V3LeagueRules.for_game("0022500884")
    jump = dict(p.jump(clock="PT05M00S"), period=5)
    order, notes = period_order(enumerate([jump, s.start(5), s.end(5)]), rules)
    assert order == (1, 0, 2) and notes
    heave = s.row("Heave", "Team Field Goal Attempt", "PT00M00S", s.HOME, s.HOME)
    rebound = p.rebound(clock="PT00M00S", pid=0, team=s.HOME)
    rows = [s.start(), s.end(), heave, rebound]
    order, notes = period_order(enumerate(rows), rules)
    assert order == (0, 2, 3, 1) and notes
    # 0022501031 has a 0.3-second closing marker: no invented clock correction.
    rows[1] = dict(rows[1], clock="PT00M00.3S")
    assert period_order(enumerate(rows), rules) == ((0, 1, 2, 3), [])


def test_replay_and_score_annotations_keep_diagnostics_and_raw_values():
    rows = [s.start(), s.shot(1, scoreHome="99", scoreAway="0"),
            s.row("Instant Replay", "Overturn Ruling", "PT09M00S"), s.end()]
    result = load(rows)
    assert result.events[1].score[s.HOME] == 2
    assert result.events[1].facts.group.primary.get("scoreHome") == "99"
    assert {d["code"] for d in result.diagnostics} == {"stale_score_annotation", "final_snapshot_replay"}
    with pytest.raises(ValueError, match="accumulated scoring"):
        load(rows, False)
    rows[1]["scoreHome"] = "2"
    with pytest.raises(ValueError, match="separate resolution"):
        load(rows, False)


def test_foul_after_free_throw_is_linked_at_exact_clock():
    rows = [s.start(), p.ft(), p.foul(), p.ft(2), s.end()]
    result = load(rows)
    assert result.events[1].trip_foul is result.events[2]
    assert result.events[3].trip_foul is result.events[2]
    with pytest.raises(ValueError, match="compatible preceding foul"):
        load(rows, False)
    rows[2] = p.foul(clock="PT09M59S")
    with pytest.raises(ValueError, match="clock increases"):
        load(rows)


def test_numbered_technical_awards_around_ejection_require_two_fouls():
    def technical(attempt):
        return s.row("Free Throw", f"Free Throw Technical {attempt} of 2", "PT10M00S", 1, s.HOME,
                     f"Player1 Free Throw Technical {attempt} of 2 ({attempt} PTS)")
    rows = [s.start(), p.foul("Technical"), s.row("Ejection", "Other", "PT10M00S", 11, s.AWAY),
            p.foul("Technical"), technical(1), technical(2), s.sub(11, 16, team=s.AWAY), s.shot(1), s.end()]
    result = load(rows)
    assert result.events[4].is_technical_ft and result.events[5].is_technical_ft
    assert not result.events[5].is_end_ft
    assert result.events[1].number_of_fta_for_foul == result.events[3].number_of_fta_for_foul == 1
    assert result.events[4].trip_foul is result.events[1]
    assert result.events[5].trip_foul is result.events[3]
    with pytest.raises(ValueError, match="technical foul awards"):
        load([s.start(), p.foul("Technical"), technical(1), technical(2), s.shot(1), s.end()])
    with pytest.raises(ValueError, match="not on court"):
        load(rows[:-2] + [s.shot(11, team=s.AWAY), s.end()])


def test_blank_turnover_is_a_turnover_with_unspecified_cause():
    result = load([s.start(), p.turnover(subtype=""), s.end()])
    assert result.events[1].is_possession_ending_event
    assert not result.events[1].is_no_turnover
    assert result.events[1].facts.subtype == ""


@pytest.mark.parametrize("game_id", prep.GAMES[1:])
def test_full_recorded_games_reconcile_with_v2_rules(tmp_path, game_id):
    prepared = prep.prepare(game_id, review=prep.reviewed(game_id), use_v2_rules=True)
    assert prepared.ready, prepared.diagnostics
    target = tmp_path / "lineups.json"
    prepared.write_lineups(target)
    result = load_game(game_id, prep.directory(game_id), snapshot_complete=True,
                       lineup_evidence=target, use_v2_rules=True)
    assert result.capabilities["processing_rules"] == "v2"
    with pytest.raises(ValueError, match="requires use_v2_rules"):
        load_game(game_id, prep.directory(game_id), snapshot_complete=True, lineup_evidence=target)
    box = result.boxscore.source_data
    box["boxScoreTraditional"]["homeTeam"]["statistics"]["points"] += 1
    with pytest.raises(ValueError, match="scoring conflicts"):
        reconcile_scoring(SimpleNamespace(source_data=box), result.possessions.events)


def test_old_projection_without_team_points_cannot_certify_replay_scoring():
    prepared = prep.prepare("0021900001", review=prep.reviewed("0021900001"), use_v2_rules=True)
    assert not prepared.ready
    assert "scoring conflicts with box score" in prepared.diagnostics[-1].message
