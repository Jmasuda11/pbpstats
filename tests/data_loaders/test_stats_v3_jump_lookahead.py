"""Recover team possession without inventing jump recipient identities."""

import json

import pytest
import test_stats_v3_lineups as s
import test_stats_v3_possessions as p
from test_stats_v3_v2_rules import lineups, load, offline
from pbpstats.data_loader.stats_nba_v3.lineups import StatsNbaV3LineupLoader, V3LineupEvidence


def unknown_jump(clock="PT12M00S"):
    return dict(p.jump(clock), description=" ")


@pytest.mark.parametrize("pid,team", [(2, s.HOME), (12, s.AWAY)])
@pytest.mark.parametrize("made", [True, False])
def test_next_attempt_establishes_team_not_recipient(pid, team, made):
    attempt = s.shot(pid, clock="PT11M45S", team=team) if made else p.miss("PT11M45S", pid, team)
    tail = [] if made else [p.rebound("PT11M44S", pid=11 if team == s.HOME else 1,
                                     team=s.AWAY if team == s.HOME else s.HOME)]
    rows = [s.start(), unknown_jump(), attempt, *tail, s.end()]
    original = json.dumps(rows)
    result = load(rows)
    jump = result.events[1]
    recipient = jump.facts.participants.participants["tip_recipient"]
    assert jump.team_id == team and jump.player1_id == 1
    assert recipient.status == "unresolved" and recipient.player_id is None
    assert recipient.team_id == team and recipient.external_sha256 is None
    assert recipient.source_indices == (1, 2)
    notice = next(d for d in result.lineups.diagnostics if d["code"] == "implied_jump_winner")
    assert notice["source_indices"] == (1, 2)
    assert "field_goal/Jump Shot" in recipient.evidence
    assert json.dumps(rows) == original
    with pytest.raises(ValueError, match="opposing_jumper"):
        load(rows, False)


def test_substitution_and_timeout_do_not_choose_a_winner_or_require_same_lineup():
    # 0022500099: Harden at 3:45, Suns sub at 3:42, Lopez basket at 3:40.
    rows = [s.start(), s.shot(11, clock="PT04M00S", team=s.AWAY),
            unknown_jump("PT03M45S"), s.sub(11, 16, clock="PT03M42S", team=s.AWAY),
            s.row("Timeout", "Regular", "PT03M42S", team=s.AWAY),
            s.shot(2, clock="PT03M40S"), s.end()]
    result = load(rows)
    recipient = result.events[2].facts.participants.participants["tip_recipient"]
    assert recipient.team_id == s.HOME and recipient.source_indices == (2, 3, 4, 5)
    assert result.events[3].current_players[s.AWAY] == (12, 13, 14, 15, 16)


@pytest.mark.parametrize("team,pid,next_team,next_pid", [(s.HOME, 1, s.AWAY, 11), (s.AWAY, 11, s.HOME, 1)])
def test_turnover_identifies_team_that_lost_control_not_next_shooter(team, pid, next_team, next_pid):
    rows = [s.start(), unknown_jump(), p.turnover("PT11M50S", pid, team),
            s.shot(next_pid, clock="PT11M40S", team=next_team), s.end()]
    result = load(rows)
    assert result.events[1].team_id == result.events[2].team_id == team
    assert result.events[3].team_id == next_team


@pytest.mark.parametrize("subtype,team", [("Offensive", s.AWAY), ("Offensive Charge", s.AWAY), ("Shooting", s.HOME)])
def test_unambiguous_foul_uses_offensive_side(subtype, team):
    result = lineups([s.start(), unknown_jump(), p.foul(subtype, clock="PT11M50S"), s.end()])
    assert result.items[1].event.participants.participants["tip_recipient"].team_id == team


@pytest.mark.parametrize("barrier", [
    p.rebound("PT11M55S"), p.ft(clock="PT11M55S"), p.ft(category="Technical", clock="PT11M55S"),
    p.foul("Loose Ball", clock="PT11M55S"), p.foul("Personal", clock="PT11M55S"),
    p.foul("Technical", clock="PT11M55S"), p.jump("PT11M55S"),
    p.turnover("PT12M00S"), p.turnover("PT11M55S", subtype=""),
    p.turnover("PT11M55S", subtype="Jump Ball Violation"),
    p.turnover("PT11M55S", subtype="Lane Violation"),
    s.row("Violation", "Jump Ball", "PT11M55S", 11, s.AWAY),
    s.row("Violation", "Kicked Ball", "PT11M55S", 11, s.AWAY),
    s.row("Instant Replay", "Support Ruling", "PT11M55S"),
    s.row("Ejection", "Other", "PT11M55S", 11, s.AWAY),
])
def test_lookahead_cannot_skip_an_ambiguous_control_event(barrier):
    with pytest.raises(ValueError, match="winning team is unresolved"):
        lineups([s.start(), unknown_jump(), barrier, s.shot(1, clock="PT11M50S"), s.end()])


def test_period_end_and_long_gaps_cannot_establish_winner():
    with pytest.raises(ValueError, match="winning team is unresolved"):
        lineups([s.start(), unknown_jump("PT00M01S"), s.end()])
    with pytest.raises(ValueError, match="winning team is unresolved"):
        lineups([s.start(), unknown_jump(), s.shot(1, clock="PT11M35S"), s.end()])


@pytest.mark.parametrize("pid,team", [(2, s.HOME), (12, s.AWAY)])
def test_cross_team_name_collision_keeps_candidates_but_infers_team(pid, team):
    facts = s.events([s.start(), s.jones_tip(), s.shot(pid, clock="PT11M45S", team=team), s.end()],
                     ctx=s.jones_context(2, 12))
    evidence = V3LineupEvidence(json.dumps(s.evidence(facts)).encode(), "test")
    result = StatsNbaV3LineupLoader(facts, evidence, use_v2_rules=True)
    recipient = result.items[1].event.participants.participants["tip_recipient"]
    assert recipient.team_id == team and recipient.player_id is None
    assert recipient.status == "ambiguous" and recipient.candidates == (2, 12)
    assert facts.items[1].participants.participants["tip_recipient"].team_id is None


def test_no_on_court_name_match_cannot_be_repaired_by_lookahead():
    facts = s.events([s.start(), s.jones_tip(), s.shot(2, clock="PT11M45S"), s.end()],
                     ctx=s.jones_context(6, 16))
    evidence = V3LineupEvidence(json.dumps(s.evidence(facts)).encode(), "test")
    with pytest.raises(ValueError, match="winning team is unresolved"):
        StatsNbaV3LineupLoader(facts, evidence, use_v2_rules=True)


def test_explicit_recovery_is_never_overwritten_and_future_actors_are_validated():
    result = lineups([s.start(), p.jump("PT12M00S"), s.shot(1, clock="PT11M45S"), s.end()])
    assert result.items[1].event.participants.participants["tip_recipient"].team_id == s.AWAY
    assert not any(d["code"] == "implied_jump_winner" for d in result.diagnostics)
    with pytest.raises(ValueError, match="not on court"):
        lineups([s.start(), unknown_jump(), s.shot(6, clock="PT11M45S"), s.end()])
