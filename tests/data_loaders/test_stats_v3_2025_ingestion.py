"""Regressions from the first 2025-26 regular-season ingestion batch."""

from dataclasses import replace
import json

import pytest
import test_stats_v3_lineups as synthetic
import test_stats_v3_participants as participants
import test_stats_v3_leagues as leagues
import test_stats_v3_possessions as plays
from pbpstats.data_loader.stats_nba_v3.context import V3RosterPlayer, V3BenchPerson
from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.lineups import StatsNbaV3LineupLoader, V3LineupEvidence, lineup_fingerprints
from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader
from pbpstats.data_loader.stats_nba_v3.preparation import _batches


@pytest.mark.parametrize("official,description", [("Dončić", "Doncic"), ("Diabaté", "Diabate"), ("Jović", "Jovic")])
def test_substitution_accent_variants_keep_original_names(official, description):
    ctx = synthetic.context()
    ctx = replace(ctx, players=tuple(replace(p, aliases=(official,)) if p.player_id == 6 else p for p in ctx.players))
    row = participants.row(kind="Substitution", person=1, description=f"SUB: {description} FOR Player1")
    result = participants.interpret([row], ctx).items[0]
    assert result.require_player("incoming") == 6
    assert ctx.player(6).aliases == (official,)
    collision = replace(ctx, players=ctx.players + (V3RosterPlayer(9, synthetic.HOME, (description,)),))
    result = participants.interpret([row], collision).items[0]
    assert result.participants["incoming"].status == "ambiguous"
    with pytest.raises(ValueError, match="ambiguous"):
        result.require_player("incoming")


def test_disjoint_substitutions_are_optional_but_chains_require_review():
    for rows, accepted_count in [([synthetic.sub(1, 6), synthetic.sub(2, 7)], 1),
                                 ([synthetic.sub(1, 6), synthetic.sub(6, 7)], 0),
                                 ([synthetic.sub(1, 6), synthetic.sub(2, 6)], 0)]:
        events = synthetic.events(rows)
        diagnostics = []
        accepted, pending = _batches(events, {}, "Complete test stream", diagnostics, True)
        assert len(accepted) == accepted_count
        assert bool(pending) == (not accepted_count)
        assert bool(diagnostics) == (not accepted_count)
    diagnostics = []
    assert not _batches(synthetic.events([synthetic.sub(1, 6), synthetic.sub(2, 7)]), {}, "Test", diagnostics)[0]


@pytest.mark.parametrize("subtype", ["Palming Turnover", "Offensive Goaltending", "Inbound Turnover", "Discontinue Dribble", "Lane Violation",
                                      "Illegal Assist Turnover", "Too Many Players Turnover", "Excess Timeout Turnover", "Punched Ball Turnover", "10 Second Violaton", "Jump Ball Violation"])
def test_new_turnover_vocabulary_ends_possession(subtype):
    game = leagues.load([synthetic.start(), plays.turnover(subtype=subtype), synthetic.end()])
    event = game.events[1]
    assert event.facts.kind == "turnover" and not event.is_steal
    assert event.is_possession_ending_event
    assert event.is_offensive_goaltending == (subtype == "Offensive Goaltending")
    assert event.is_lane_violation == (subtype == "Lane Violation")


def test_substitution_name_variant_is_bound_to_recorded_outgoing_id():
    incoming = dict(synthetic.sub(1, 6), description="SUB: Hansen FOR Player1")
    outgoing = dict(synthetic.sub(6, 1), description="SUB: Player1 FOR Hansen")
    facts = synthetic.events([incoming, outgoing])
    person = facts.items[0].participants.participants["incoming"]
    assert person.player_id == 6 and person.source_indices == (0, 1)
    assert "explicit outgoing personId" in person.evidence
    # Every ID using that recorded name remains a candidate; no first-match win.
    collision = dict(synthetic.sub(7, 2), description="SUB: Player2 FOR Hansen")
    facts = synthetic.events([incoming, outgoing, collision])
    assert facts.items[0].participants.participants["incoming"].candidates == (6, 7)
    with pytest.raises(ValueError, match="ambiguous"):
        facts.items[0].participants.require_player("incoming")


def test_given_name_requires_full_name_and_family_alias_and_preserves_collisions():
    ctx = synthetic.context()
    ctx = replace(ctx, players=tuple(replace(p, name="Hansen Yang", aliases=("Hansen Yang", "Yang", "H. Yang"))
                                    if p.player_id == 6 else p for p in ctx.players))
    row = participants.row(kind="Substitution", person=1, description="SUB: Hansen FOR Player1")
    assert participants.interpret([row], ctx).items[0].require_player("incoming") == 6
    assert ctx.candidates("Hans") == ()
    assert ctx.player(6).aliases == ("Hansen Yang", "Yang", "H. Yang")
    collision = replace(ctx, players=ctx.players + (V3RosterPlayer(9, synthetic.HOME, ("Hansen",)),))
    result = participants.interpret([row], collision).items[0]
    assert result.participants["incoming"].candidates == (6, 9)
    with pytest.raises(ValueError, match="ambiguous"):
        result.require_player("incoming")


def test_marked_first_name_abbreviations_preserve_initial_collisions():
    ctx = synthetic.context()
    names = {6: ("Jaylin", "Williams"), 7: ("Jalen", "Williams"),
             16: ("Stephen", "Curry"), 17: ("Seth", "Curry")}
    ctx = replace(ctx, players=tuple(replace(p, name=" ".join(names[p.player_id]),
                      aliases=(" ".join(names[p.player_id]), names[p.player_id][1],
                               names[p.player_id][0][0] + ". " + names[p.player_id][1]))
                      if p.player_id in names else p for p in ctx.players))
    assert ctx.candidates("Jay. Williams") == (6,)
    assert ctx.candidates("Jal. Williams") == (7,)
    assert ctx.candidates("St. Curry") == (16,)
    assert ctx.candidates("Se. Curry") == (17,)
    assert ctx.candidates("J. Williams") == ctx.candidates("Ja. Williams") == (6, 7)
    assert ctx.candidates("S. Curry") == (16, 17)
    assert ctx.candidates("Jay Williams") == ()


@pytest.mark.parametrize("subtype", ["Delay Technical", "Bench", "Flopping", "Excess Timeout Technical", "Too Many Players Technical", "Non-Unsportsmanlike Technical"])
def test_extra_technical_types_require_one_ft_without_personal_or_team_foul(subtype):
    rows = [synthetic.start(), plays.foul(subtype), plays.ft(category="Technical"), synthetic.shot(1), synthetic.end()]
    game = leagues.load(rows)
    foul, ft = game.events[1:3]
    assert ft.trip_foul is foul and foul.is_technical
    assert not foul.counts_as_personal_foul and not foul.counts_towards_penalty
    assert foul.is_delay_of_game == (subtype == "Delay Technical")
    with pytest.raises(ValueError, match="missing free-throw trip"):
        leagues.load([rows[0], rows[1], *rows[3:]])


@pytest.mark.parametrize("subtype,description", [
    ("Double Personal", " Foul : Double Personal - Player11 (1 PF), Player1 (1 PF) (Referee)"),
    ("Double Technical", "Double Technical - Player11, Player1 (Referee)"),
])
def test_double_fouls_attribute_both_players_and_do_not_award_free_throws(subtype, description):
    game = leagues.load([synthetic.start(), dict(plays.foul(subtype), description=description), synthetic.shot(1), synthetic.end()])
    event = game.events[1]
    assert event.player1_id == 11 and event.player3_id == 1
    assert not event.counts_towards_penalty and not event.is_technical
    assert event.is_double_foul == (subtype == "Double Personal")
    assert event.is_double_technical == (subtype == "Double Technical")
    assert event.player_game_fouls[11] == event.player_game_fouls[1] == (subtype == "Double Personal")
    assert event.fouls_to_give == event.fouls_to_give_before


def test_double_personal_foul_requires_an_on_court_opponent():
    row = dict(plays.foul("Double Personal"), description="Foul : Double Personal - Player11 (1 PF), Player6 (1 PF) (Referee)")
    with pytest.raises(ValueError, match="not on court"):
        leagues.load([synthetic.start(), row, synthetic.shot(1), synthetic.end()])


def test_challenge_jump_and_altercation_replay_keep_possession_semantics():
    jump = dict(plays.jump("PT12M00S"), subType="Coach Challenge")
    replay = synthetic.row("Instant Replay", "Altercation Ruling", "PT10M00S", 0, 0, "Instant Replay")
    shot = synthetic.shot(12, "PT10M00S", team=synthetic.AWAY)
    game = leagues.load([synthetic.start(), jump, shot, replay, synthetic.end()])
    assert game.events[1].team_id == synthetic.AWAY
    assert game.events[3].facts.kind == "replay"


def test_post_period_replay_does_not_create_an_extra_possession():
    rows = [synthetic.start(), synthetic.shot(1, clock="PT01M00S"), synthetic.end()]
    baseline = leagues.load(rows)
    replay = synthetic.row("Instant Replay", "Support Ruling", "PT00M00S", 0, 0, "Instant Replay")
    game = leagues.load([*rows, replay])
    assert len(game.events) == len(baseline.events) + 1
    assert game.counts_by_team == baseline.counts_by_team
    assert len(game.items) == len(baseline.items)
    with pytest.raises(ValueError, match="outside a started period"):
        leagues.load([*rows, dict(replay, clock="PT00M01S")])
    with pytest.raises(ValueError, match="outside a started period"):
        leagues.load([*rows, synthetic.shot(1, clock="PT00M00S")])


def test_loose_ball_award_after_teammates_make():
    rows = [synthetic.start(), synthetic.shot(2, "PT10M00S"), plays.foul("Loose Ball"), plays.ft(total=1), synthetic.end()]
    game = leagues.load(rows)
    shot, foul, ft = game.events[1:4]
    assert ft.trip_foul is foul and shot._and_one is ft
    assert not shot.is_possession_ending_event and ft.is_possession_ending_event
    with pytest.raises(ValueError, match="compatible preceding foul"):
        leagues.load([rows[0], synthetic.shot(2, "PT10M01S"), *rows[2:]])
    with pytest.raises(ValueError, match="compatible preceding foul"):
        leagues.load([rows[0], rows[1], plays.foul("Personal"), *rows[3:]])


def test_blocked_team_heave_preserves_blocker_without_shooter():
    gid = "0022500082"
    ctx = replace(synthetic.context(), game_id=gid)
    rows = [synthetic.start(),
            synthetic.row("Heave", "Team Field Goal Attempt", "PT00M00.70S", 0, synthetic.HOME, "Team Heave"),
            synthetic.row("", "", "PT00M00.70S", 0, synthetic.AWAY, "Player11 BLOCK (2 BLK)"),
            plays.rebound("PT00M00.10S", pid=0, team=synthetic.HOME), synthetic.end()]
    rows = [dict(r, actionId=i+1, actionNumber=2 if i==2 else i+1) for i, r in enumerate(rows)]
    raw = participants.raw_loader(rows, gid)
    resolved = participants.StatsNbaV3ParticipantLoader(raw, ctx, snapshot_complete=True)
    facts = StatsNbaV3EventLoader(resolved)
    evidence = dict(schema_version=1, game_id=gid, **lineup_fingerprints(facts),
                    periods=[synthetic.period_evidence()], batches=[])
    game = StatsNbaV3PossessionLoader(StatsNbaV3LineupLoader(facts, V3LineupEvidence(json.dumps(evidence).encode(), "Test")))
    heave = game.events[1]
    assert heave.is_blocked and heave.player3_id == 11
    assert heave.player1_id == 0 and heave.shot_value is None
    assert heave.facts.group.source_indices == (1, 2)
    assert raw.data == rows


def test_nba_heave_rule_includes_fourth_quarter_but_not_overtime():
    rules = replace(synthetic.context(), game_id="0022500082").rules
    assert rules.team_heave(4, 3)
    assert not rules.team_heave(4, 4)
    assert not rules.team_heave(5, 0)


def test_two_coach_technicals_and_ejection_preserve_players_and_two_awards():
    ctx = replace(synthetic.context(), game_id="0022500001",
                  bench_people=(V3BenchPerson(999, synthetic.AWAY, "Test Coach", "Official coach source"),))
    foul = synthetic.row("Foul", "Technical", "PT10M00S", 999, 0, "Test Coach Foul:T.FOUL (Referee)")
    ejection = dict(foul, actionType="Ejection", subType="Other", description="Test Coach Ejection:Other")
    rows = [synthetic.start(), foul, foul, ejection, plays.ft(category="Technical"), plays.ft(category="Technical"), synthetic.shot(1), synthetic.end()]
    game = leagues.load(rows, ctx=ctx)
    assert game.events[4].trip_foul is game.events[1]
    assert game.events[5].trip_foul is game.events[2]
    assert game.events[3].player1_id == 0
    assert game.events[3].lineup.before == game.events[3].lineup.after
    with pytest.raises(ValueError, match="missing free-throw trip"):
        leagues.load(rows[:5] + rows[6:], ctx=ctx)
    with pytest.raises(ValueError, match="ejected bench person"):
        leagues.load(rows[:4] + [foul] + rows[4:], ctx=ctx)


def test_paired_double_lane_cancels_final_ft_and_uses_recorded_jump():
    violations = [synthetic.row("Violation", "Double Lane", "PT10M00S", pid, team, "Double Lane")
                  for pid, team in [(2, synthetic.HOME), (12, synthetic.AWAY)]]
    rows = [synthetic.start(), plays.foul(), plays.ft(), *violations,
            plays.jump("PT10M00S"), synthetic.shot(12, team=synthetic.AWAY), synthetic.end()]
    game = leagues.load(rows)
    assert len([e for e in game.events if e.facts.kind == "free_throw"]) == 1
    assert game.events[2].facts.free_throw.total == 2
    assert game.events[2].is_made and not game.events[2].is_end_ft
    assert game.events[5].team_id == synthetic.AWAY
    assert not game.events[2].is_possession_ending_event
    with pytest.raises(ValueError, match="opposing violations"):
        leagues.load(rows[:4] + rows[5:])
    with pytest.raises(ValueError, match="opposing violations"):
        leagues.load(rows[:4] + [dict(violations[1], personId=3, teamId=synthetic.HOME, location="h")] + rows[5:])
    with pytest.raises(ValueError, match="same-clock jump"):
        leagues.load(rows[:5] + rows[6:])
    with pytest.raises(ValueError, match="does not start at attempt 1"):
        leagues.load(rows[:6] + [plays.ft(attempt=2)] + rows[6:])
