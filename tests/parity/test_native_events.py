"""Native V3 event classes decide as the original's classes do for every label."""

import pytest

from pbpstats.data_loader.stats_nba_v3.decoder import (
    CLEAR_PATH_FREE_THROWS,
    FLAGRANT_FREE_THROWS,
    FOULS,
    FREE_THROWS,
    JUMP_BALLS,
    REBOUNDS,
    REPLAYS,
    SHOT_CODES,
    TECHNICAL_FREE_THROWS,
    TURNOVERS,
    VIOLATIONS,
    WNBA_CLEAR_PATH_FREE_THROWS,
)
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

HOME, AWAY = 1610612737, 1610612738
FREE_THROW_TABLES = {
    "Free Throw": FREE_THROWS,
    "Free Throw Flagrant": FLAGRANT_FREE_THROWS,
    "Free Throw Clear Path": {**CLEAR_PATH_FREE_THROWS, **WNBA_CLEAR_PATH_FREE_THROWS},
    "Free Throw Technical": TECHNICAL_FREE_THROWS,
}
FREE_THROW_LABELS = [("Free Throw Technical", 16)] + [
    (f"{name} {attempt} of {total}", code)
    for name, table in FREE_THROW_TABLES.items()
    for (attempt, total), code in table.items()
]


def row(event_type, code, action_type, sub_type, **people):
    """A decoded row: V2's codes for the original, V3's labels for native classes."""
    event = dict(
        GAME_ID="0022400001",
        EVENTNUM=10,
        PERIOD=1,
        PCTIMESTRING="5:00",
        EVENTMSGTYPE=event_type,
        EVENTMSGACTIONTYPE=code,
        PLAYER1_ID=0,
        PLAYER1_TEAM_ID=None,
        NEUTRALDESCRIPTION="",
        V3_ACTION_TYPE=action_type,
        V3_SUB_TYPE=sub_type,
    )
    event.update(people)
    return event


def same(native, original, names):
    for name in names:
        assert getattr(native, name) == getattr(original, name), name


@pytest.mark.parametrize("label, code", sorted(REPLAYS.items()))
def test_replay_rulings(label, code):
    event = row(18, code, "Instant Replay", label)
    same(
        StatsNbaV3Replay(event, 0),
        StatsReplay(event, 0),
        ("support_ruling", "overturn_ruling", "ruling_stands"),
    )


@pytest.mark.parametrize("label, code", sorted(SHOT_CODES.items()))
@pytest.mark.parametrize("event_type, action_type", [(1, "Made Shot"), (2, "Missed Shot")])
@pytest.mark.parametrize("value", ["", " 3PT "], ids=["2pt", "3pt"])
def test_field_goals(label, code, event_type, action_type, value):
    event = row(
        event_type, code, action_type, label, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME,
        NEUTRALDESCRIPTION=f"Player 24'{value}{label}",
    )
    same(StatsNbaV3FieldGoal(event, 0), StatsFieldGoal(event, 0), ("is_made", "shot_value"))


@pytest.mark.parametrize("label, code", FREE_THROW_LABELS)
@pytest.mark.parametrize("miss", ["", "MISS "], ids=["made", "missed"])
def test_free_throws(label, code, miss):
    event = row(
        3, code, "Free Throw", label, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME,
        NEUTRALDESCRIPTION=f"{miss}Player {label}",
    )
    same(
        StatsNbaV3FreeThrow(event, 0),
        StatsFreeThrow(event, 0),
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


@pytest.mark.parametrize("label, code", sorted(FOULS.items()))
def test_fouls(label, code):
    event = row(6, code, "Foul", label, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME)
    same(
        StatsNbaV3Foul(event, 0),
        StatsFoul(event, 0),
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


@pytest.mark.parametrize("label, code", sorted(VIOLATIONS.items()))
def test_violations(label, code):
    event = row(7, code, "Violation", label, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME)
    same(
        StatsNbaV3Violation(event, 0),
        StatsViolation(event, 0),
        (
            "is_delay_of_game",
            "is_goaltend_violation",
            "is_lane_violation",
            "is_jumpball_violation",
            "is_kicked_ball_violation",
            "is_double_lane_violation",
        ),
    )


@pytest.mark.parametrize("label, code", sorted(REBOUNDS.items()))
@pytest.mark.parametrize("rebounder", [201, 0], ids=["player", "team"])
def test_rebound_placeholders(label, code, rebounder):
    event = row(4, code, "Rebound", label, PLAYER1_ID=rebounder, PLAYER1_TEAM_ID=HOME)
    same(StatsNbaV3Rebound(event, 0), StatsRebound(event, 0), ("is_placeholder",))


@pytest.mark.parametrize("label, code", sorted(TURNOVERS.items()))
@pytest.mark.parametrize("stealer", [301, None], ids=["stolen", "not stolen"])
def test_turnovers(label, code, stealer):
    event = row(
        5, code, "Turnover", label, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME, PLAYER2_ID=stealer
    )
    same(
        StatsNbaV3Turnover(event, 0),
        StatsTurnover(event, 0),
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
    event = row(8, 0, "Substitution", "", PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME, PLAYER2_ID=202)
    native, original = StatsNbaV3Substitution(event, 0), StatsSubstitution(event, 0)
    same(native, original, ("outgoing_player_id", "incoming_player_id"))
    assert (native.outgoing_player_id, native.incoming_player_id) == (201, 202)


@pytest.mark.parametrize("label, code", sorted(JUMP_BALLS.items()))
@pytest.mark.parametrize(
    "recipient, recipient_team",
    [(203, HOME), (AWAY, None)],
    ids=["tipped to a player", "tipped out of bounds"],
)
def test_jump_ball_participants(label, code, recipient, recipient_team):
    event = row(
        10, code, "Jump Ball", label, PLAYER1_ID=201, PLAYER1_TEAM_ID=HOME,
        PLAYER2_ID=301, PLAYER3_ID=recipient, PLAYER3_TEAM_ID=recipient_team,
    )
    native, original = StatsNbaV3JumpBall(event, 0), StatsJumpBall(event, 0)
    same(native, original, ("team_id", "winning_team", "player1_id", "player3_id"))
    assert hasattr(native, "player2_id") == hasattr(original, "player2_id")
    assert getattr(native, "player2_id", None) == getattr(original, "player2_id", None)


def test_native_events_never_read_v2_action_codes():
    native = StatsNbaV3Replay(row(18, 4, "Instant Replay", "Coach Challenge Support Ruling"), 0)
    assert native.sub_type == "Coach Challenge Support Ruling"
    assert not hasattr(native, "event_action_type")


def test_native_events_print_as_the_original_does():
    event = row(18, 4, "Instant Replay", "Coach Challenge Support Ruling")
    assert repr(StatsNbaV3Replay(event, 0)) == repr(StatsReplay(event, 0))
