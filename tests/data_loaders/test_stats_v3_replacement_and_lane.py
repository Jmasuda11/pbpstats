"""Use recorded actors without assuming jump winners or injury diagnoses."""

import pytest
import json
import test_stats_v3_lineups as s
import test_stats_v3_possessions as p
from test_stats_v3_v2_rules import load, offline
from pbpstats.data_loader.stats_nba_v3.lineups import StatsNbaV3LineupLoader, V3LineupEvidence
from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader


def test_known_jump_actor_does_not_establish_winner():
    jump = dict(p.jump("PT12M00S"), description=" ")
    with pytest.raises(ValueError, match="winning team is unresolved"):
        load([s.start(), jump, s.end()])


def test_winner_is_enough_without_identifying_opposing_jumper():
    jump = dict(p.jump("PT12M00S"), description="Jump Ball Player1 vs. Unknown: Tip to Player12")
    rows = [s.start(), jump, s.shot(12, team=s.AWAY), s.end()]
    result = load(rows)
    event = result.events[1]
    assert event.player1_id == 1  # The source actor remains the home player.
    assert event.team_id == s.AWAY  # Possession follows the recipient's team.
    opponent = event.facts.participants.participants["opposing_jumper"]
    assert opponent.player_id is None and opponent.status == "unresolved"
    assert result.lineups.diagnostics[0]["code"] == "unknown_opposing_jumper"
    with pytest.raises(ValueError, match="opposing_jumper"):
        load(rows, False)
    rows[1] = dict(jump, description="Jump Ball Player1 vs. Player16: Tip to Player12")
    with pytest.raises(ValueError, match="not on court"):
        load(rows)


@pytest.mark.parametrize("players, known_team", [((2, 3), s.HOME), ((12, 13), s.AWAY), ((2, 12), None)])
def test_ambiguous_recipient_can_only_establish_team_if_all_candidates_agree(players, known_team):
    tail = [s.shot(players[0], team=known_team)] if known_team else []
    facts = s.events([s.start(), s.jones_tip(), *tail, s.end()],
                     ctx=s.jones_context(*players))
    evidence = V3LineupEvidence(json.dumps(s.evidence(facts)).encode(), "test")
    if known_team is None:
        with pytest.raises(ValueError, match="winning team is unresolved"):
            StatsNbaV3LineupLoader(facts, evidence, use_v2_rules=True)
    else:
        lineups = StatsNbaV3LineupLoader(facts, evidence, use_v2_rules=True)
        result = StatsNbaV3PossessionLoader(lineups)
        recipient = result.events[1].facts.participants.participants["tip_recipient"]
        assert recipient.player_id is None and recipient.status == "ambiguous"
        assert recipient.candidates == players and recipient.team_id == known_team
        assert result.events[1].team_id == known_team


@pytest.mark.parametrize("substituted", [False, True])
def test_and_one_can_be_shot_by_different_recorded_player(substituted):
    rows = [s.start(), s.shot(1, clock="PT10M00S"), p.foul(foulDrawnPersonId=1)]
    if substituted:
        rows.append(s.sub(1, 6))
    rows += [p.ft(total=1, pid=6 if substituted else 2), s.end()]
    result = load(rows)
    basket, foul, ft = result.events[1], result.events[2], result.events[-2]
    assert basket.is_and1 and not basket.is_possession_ending_event
    assert ft.is_possession_ending_event and ft.trip_foul is foul
    assert basket.player1_id == foul.player3_id == 1
    assert ft.player1_id == (6 if substituted else 2)
    assert result.events[-1].score[s.HOME] == 3
    assert any(d["code"] == "different_shooter_after_made_basket" for d in result.diagnostics)
    with pytest.raises(ValueError, match="replacement shooter"):
        load(rows, False)


def test_shooter_change_during_trip_keeps_foul_and_attempt_numbers():
    rows = [s.start(), p.foul(foulDrawnPersonId=1), p.ft(), s.sub(1, 6), p.ft(2, pid=6), s.end()]
    result = load(rows)
    first, last = result.events[2], result.events[4]
    assert first.player1_id == 1 and last.player1_id == 6
    assert first.trip_foul is last.trip_foul is result.events[1]
    assert first.facts.free_throw.attempt == 1 and last.facts.free_throw.attempt == 2
    assert any(d["code"] == "recorded_shooter_change" for d in result.diagnostics)
    with pytest.raises(ValueError, match="conflicting free-throw trip"):
        load(rows, False)


def test_personal_foul_basket_award_does_not_require_same_scorer():
    # 0022500090: da Silva basket, Kennard personal foul, Bitadze one FT.
    rows = [s.start(), s.shot(1, clock="PT10M00S"), p.foul("Personal"), p.ft(total=1, pid=2), s.end()]
    result = load(rows)
    assert result.events[1].is_and1
    assert result.events[3].trip_foul is result.events[2]
    with pytest.raises(ValueError, match="compatible preceding foul"):
        load(rows, False)


@pytest.mark.parametrize("rows, error", [
    ([s.start(), s.shot(1, clock="PT10M00S"), p.foul(), p.ft(total=1, pid=6), s.end()], "not on court"),
    ([s.start(), p.foul(), p.ft(total=1, pid=2), s.end()], "unique matching and-one"),
    ([s.start(), s.shot(1, clock="PT10M00S"), s.shot(2, clock="PT10M00S"), p.foul(), p.ft(total=1, pid=3), s.end()], "unique matching and-one"),
    ([s.start(), p.foul(), p.foul(), p.ft(), p.ft(2, pid=2), s.end()], "one unconsumed compatible foul"),
    ([s.start(), p.foul(), p.ft(), dict(p.ft(2, pid=11), teamId=s.AWAY, location="v"), s.end()], "conflicting free-throw trip"),
])
def test_replacement_support_does_not_relax_other_trip_checks(rows, error):
    with pytest.raises(ValueError, match=error):
        load(rows)


def test_shooter_lane_violation_survives_timeout_and_substitutions():
    # 0022500110: final miss, opponent team rebound, shooter violation, timeout.
    lane = s.row("Violation", "Lane", "PT10M00S", 1, s.HOME, "Lane")
    timeout = s.row("Timeout", "Regular", "PT10M00S")
    rows = [s.start(), p.foul(), p.ft(), p.ft(2, miss=True),
            p.rebound("PT10M00S", pid=0, team=s.AWAY), lane, timeout,
            s.sub(2, 6), s.shot(11, team=s.AWAY), s.end()]
    result = load(rows)
    assert len([e for e in result.events if e.facts.kind == "free_throw"]) == 2
    assert result.events[4].is_real_rebound and result.events[4].is_possession_ending_event
    assert not result.events[5].is_possession_ending_event
    assert any(d["code"] == "lane_ruling_recorded_sequence" for d in result.diagnostics)
    with pytest.raises(ValueError, match="lane ruling"):
        load(rows, False)


def test_defensive_lane_between_attempts_uses_recorded_final_attempt():
    lane = s.row("Violation", "Lane", "PT10M00S", 11, s.AWAY, "Lane")
    rows = [s.start(), p.foul(), p.ft(), s.sub(2, 6), lane,
            p.ft(2, miss=True), p.rebound("PT09M58S"), s.shot(11, team=s.AWAY), s.end()]
    result = load(rows)
    assert len([e for e in result.events if e.facts.kind == "free_throw"]) == 2
    assert not result.events[4].is_possession_ending_event
    assert result.events[6].is_possession_ending_event


def test_lane_label_cannot_fill_missing_attempts_or_create_context():
    lane = s.row("Violation", "Lane", "PT10M00S", 11, s.AWAY, "Lane")
    with pytest.raises(ValueError, match="no same-clock"):
        load([s.start(), lane, s.shot(1), s.end()])
    with pytest.raises(ValueError, match="incomplete free-throw trip"):
        load([s.start(), p.foul(), p.ft(), lane, s.shot(1), s.end()])


@pytest.mark.parametrize("subtype", ["Lane Violation", ""])
@pytest.mark.parametrize("miss", [False, True])
def test_recorded_turnover_can_end_trip_without_a_final_attempt(subtype, miss):
    rows = [s.start(), p.foul(), p.ft(miss=miss)]
    if miss:
        rows.append(p.rebound("PT10M00S", pid=0, team=s.HOME))
    rows += [p.turnover("PT10M00S", pid=2, subtype=subtype), s.shot(11, team=s.AWAY), s.end()]
    result = load(rows)
    fts = [e for e in result.events if e.facts.kind == "free_throw"]
    assert len(fts) == 1 and fts[0].facts.free_throw.total == 2
    assert fts[0].facts.free_throw.attempt == 1 and not fts[0].is_end_ft
    turnover = result.events[-3]
    assert turnover.facts.subtype == subtype and turnover.is_possession_ending_event
    with pytest.raises(ValueError, match="interrupts free-throw trip"):
        load(rows, False)
    # A turnover by the other team cannot explain the shooting team's missing FT.
    rows[-3] = p.turnover("PT10M00S", pid=11, team=s.AWAY, subtype=subtype)
    with pytest.raises(ValueError, match="interrupts free-throw trip"):
        load(rows)
