"""Native V3 event classes decide as the original's classes do for every label."""

import pytest

from pbpstats.resources.enhanced_pbp.stats_nba import (
    StatsFieldGoal,
    StatsFoul,
    StatsFreeThrow,
    StatsJumpBall,
    StatsRebound,
    StatsReplay,
    StatsSubstitution,
    StatsTurnover,
    StatsViolation,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3 import (
    StatsNbaV3FieldGoal,
    StatsNbaV3Foul,
    StatsNbaV3FreeThrow,
    StatsNbaV3JumpBall,
    StatsNbaV3Rebound,
    StatsNbaV3Replay,
    StatsNbaV3Substitution,
    StatsNbaV3Turnover,
    StatsNbaV3Violation,
)
from tools.parity.v2_codes import labels

HOME, AWAY = 1610612737, 1610612738


def original(event_type, code, **fields):
    """A V2 row, as the original's class reads one."""
    return dict(
        dict(
            GAME_ID="0022400001",
            EVENTNUM=10,
            PERIOD=1,
            PCTIMESTRING="5:00",
            EVENTMSGTYPE=event_type,
            EVENTMSGACTIONTYPE=code,
            PLAYER1_ID=0,
            PLAYER1_TEAM_ID=None,
            NEUTRALDESCRIPTION="",
        ),
        **fields,
    )


def native(action_type, sub_type, **facts):
    """The same event's facts, as the native class reads them."""
    return dict(
        dict(
            game_id="0022400001",
            event_num=10,
            period=1,
            clock="5:00",
            description="",
            action_type=action_type,
            sub_type=sub_type,
            team_id=None,
            player1_id=0,
            player2_id=None,
            player3_id=None,
        ),
        **facts,
    )


def same(native, original, names):
    for name in names:
        assert getattr(native, name) == getattr(original, name), name


@pytest.mark.parametrize("label, code", labels("Instant Replay"))
def test_replay_rulings(label, code):
    same(
        StatsNbaV3Replay(native("Instant Replay", label), 0),
        StatsReplay(original(18, code), 0),
        ("support_ruling", "overturn_ruling", "ruling_stands"),
    )


@pytest.mark.parametrize("label, code", labels("Made Shot"))
@pytest.mark.parametrize("event_type, action_type", [(1, "Made Shot"), (2, "Missed Shot")])
@pytest.mark.parametrize("value", ["", " 3PT "], ids=["2pt", "3pt"])
def test_field_goals(label, code, event_type, action_type, value):
    text = f"Player 24'{value}{label}"
    same(
        StatsNbaV3FieldGoal(
            native(action_type, label, player1_id=201, team_id=HOME, description=text), 0
        ),
        StatsFieldGoal(
            original(
                event_type, code, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME, NEUTRALDESCRIPTION=text
            ),
            0,
        ),
        ("is_made", "shot_value"),
    )


@pytest.mark.parametrize("label, code", labels("Free Throw"))
@pytest.mark.parametrize("miss", ["", "MISS "], ids=["made", "missed"])
def test_free_throws(label, code, miss):
    text = f"{miss}Player {label}"
    same(
        StatsNbaV3FreeThrow(
            native("Free Throw", label, player1_id=201, team_id=HOME, description=text), 0
        ),
        StatsFreeThrow(
            original(3, code, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME, NEUTRALDESCRIPTION=text), 0
        ),
        (
            "is_made",
            "is_ft_1_of_1",
            "is_ft_1_of_2",
            "is_ft_2_of_2",
            "is_ft_1_of_3",
            "is_ft_2_of_3",
            "is_ft_3_of_3",
            "is_technical_ft",
            "is_flagrant_ft",
            "is_ft_1pt",
            "is_ft_2pt",
            "is_ft_3pt",
        ),
    )


@pytest.mark.parametrize("label, code", labels("Foul"))
def test_fouls(label, code):
    same(
        StatsNbaV3Foul(native("Foul", label, player1_id=201, team_id=HOME), 0),
        StatsFoul(original(6, code, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME), 0),
        (
            "is_personal_foul",
            "is_shooting_foul",
            "is_loose_ball_foul",
            "is_offensive_foul",
            "is_inbound_foul",
            "is_away_from_play_foul",
            "is_clear_path_foul",
            "is_double_foul",
            "is_technical",
            "is_flagrant",
            "is_flagrant1",
            "is_flagrant2",
            "is_double_technical",
            "is_defensive_3_seconds",
            "is_delay_of_game",
            "is_charge",
            "is_personal_block_foul",
            "is_personal_take_foul",
            "is_shooting_block_foul",
            "is_transition_take_foul",
            "counts_towards_penalty",
            "counts_as_personal_foul",
            "foul_type_string",
        ),
    )


@pytest.mark.parametrize("label, code", labels("Violation"))
def test_violations(label, code):
    same(
        StatsNbaV3Violation(native("Violation", label, player1_id=201, team_id=HOME), 0),
        StatsViolation(original(7, code, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME), 0),
        (
            "is_delay_of_game",
            "is_goaltend_violation",
            "is_lane_violation",
            "is_jumpball_violation",
            "is_kicked_ball_violation",
            "is_double_lane_violation",
        ),
    )


@pytest.mark.parametrize("label, code", labels("Rebound"))
@pytest.mark.parametrize("rebounder", [201, 0], ids=["player", "team"])
def test_rebound_placeholders(label, code, rebounder):
    same(
        StatsNbaV3Rebound(native("Rebound", label, player1_id=rebounder, team_id=HOME), 0),
        StatsRebound(original(4, code, PLAYER1_ID=rebounder, PLAYER1_TEAM_ID=HOME), 0),
        ("is_placeholder",),
    )


@pytest.mark.parametrize("label, code", labels("Turnover"))
@pytest.mark.parametrize("stealer", [301, None], ids=["stolen", "not stolen"])
def test_turnovers(label, code, stealer):
    # V2 records the stealer as its second player, the original's player 3.
    same(
        StatsNbaV3Turnover(
            native("Turnover", label, player1_id=201, team_id=HOME, player3_id=stealer), 0
        ),
        StatsTurnover(
            original(5, code, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME, PLAYER2_ID=stealer), 0
        ),
        (
            "is_steal",
            "is_no_turnover",
            "is_bad_pass",
            "is_lost_ball",
            "is_travel",
            "is_3_second_violation",
            "is_shot_clock_violation",
            "is_offensive_goaltending",
            "is_lane_violation",
            "is_kicked_ball",
            "is_step_out_of_bounds",
            "is_lost_ball_out_of_bounds",
            "is_bad_pass_out_of_bounds",
        ),
    )


def test_substitution_players():
    event = StatsNbaV3Substitution(
        native("Substitution", "", player1_id=201, team_id=HOME, player2_id=202), 0
    )
    same(
        event,
        StatsSubstitution(original(8, 0, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME, PLAYER2_ID=202), 0),
        ("outgoing_player_id", "incoming_player_id"),
    )
    assert (event.outgoing_player_id, event.incoming_player_id) == (201, 202)


@pytest.mark.parametrize("label, code", labels("Jump Ball"))
@pytest.mark.parametrize(
    "recipient, recipient_team",
    [(203, HOME), (AWAY, None)],
    ids=["tipped to a player", "tipped out of bounds"],
)
def test_jump_ball_participants(label, code, recipient, recipient_team):
    # V2 records the other jumper second and the recipient third, with the
    # recipient's team, or the team itself when no player recovered the tip.
    event = StatsNbaV3JumpBall(
        native(
            "Jump Ball", label, player1_id=201, team_id=recipient_team or recipient,
            player2_id=recipient if recipient_team else None, player3_id=301,
        ),
        0,
    )
    v2 = StatsJumpBall(
        original(
            10, code, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME,
            PLAYER2_ID=301, PLAYER3_ID=recipient, PLAYER3_TEAM_ID=recipient_team,
        ),
        0,
    )
    same(event, v2, ("team_id", "winning_team", "player1_id", "player3_id"))
    assert hasattr(event, "player2_id") == hasattr(v2, "player2_id")
    assert getattr(event, "player2_id", None) == getattr(v2, "player2_id", None)


def test_native_events_carry_no_v2_code():
    event = StatsNbaV3Replay(native("Instant Replay", "Coach Challenge Support Ruling"), 0)
    assert event.sub_type == "Coach Challenge Support Ruling"
    assert not hasattr(event, "event_type") and not hasattr(event, "event_action_type")


def test_native_events_print_as_the_original_does():
    label = "Coach Challenge Support Ruling"
    assert repr(StatsNbaV3Replay(native("Instant Replay", label), 0)) == repr(
        StatsReplay(original(18, 4), 0)
    )
