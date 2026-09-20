"""Characterize recorded inputs; these are not tests of a V3 parser yet.

Each expectation is scoped to these snapshots. Keep the raw inputs intact when
adding normalization and use these examples to test the eventual provider.
"""
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from pbpstats.data_loader.stats_nba.possessions.file import StatsNbaPossessionFileLoader
from pbpstats.data_loader.stats_nba.possessions.loader import StatsNbaPossessionLoader
from pbpstats.resources.possessions.possessions import Possessions

DATA = Path(__file__).parent / "data"
FULL_GAMES = ("0021900001", "0022400001")


def load_json(relative_path):
    return json.loads((DATA / relative_path).read_text(encoding="utf-8"))


def actions(game_id):
    return load_json(f"pbp/stats_v3_{game_id}.json")["game"]["actions"]


def v2_rows():
    payload = load_json("pbp/stats_0021900001.json")
    table = next(t for t in payload["resultSets"] if t["name"] == "PlayByPlay")
    return [dict(zip(table["headers"], row)) for row in table["rowSet"]]


@pytest.mark.parametrize("fixture", load_json("v3/manifest.json")["fixtures"])
def test_fixture_provenance_and_scope(fixture):
    raw = (DATA / fixture["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == fixture["sha256"]
    game = json.loads(raw)["game"]
    assert game["gameId"] == fixture["game_id"]
    assert len(game["actions"]) == fixture["actions"]
    if fixture["kind"] == "excerpt":
        assert fixture["complete_game"] is False
        assert len(fixture["source"]["action_indices"]) == len(game["actions"])
    else:
        assert fixture["complete_game"] is True
        assert fixture["source"]["sha256"] == fixture["sha256"]


@pytest.mark.parametrize(
    "game_id, expected_secondary",
    [
        ("0021900001", {"STEAL": 11, "BLOCK": 12}),
        ("0022400001", {"STEAL": 23, "BLOCK": 7}),
    ],
)
def test_repeated_action_numbers_preserve_secondary_participants(
    game_id, expected_secondary
):
    rows = actions(game_id)
    assert len({row["actionId"] for row in rows}) == len(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[row["actionNumber"]].append(row)
    secondary_counts = Counter()
    for group in groups.values():
        primary = [row for row in group if row["actionType"]]
        assert len(primary) == 1
        assert len({(row["period"], row["clock"]) for row in group}) == 1
        if len(group) == 1:
            continue
        assert len(group) == 2
        secondary = next(row for row in group if not row["actionType"])
        kind = "STEAL" if "STEAL" in secondary["description"] else "BLOCK"
        assert kind in secondary["description"]
        assert primary[0]["actionType"] == (
            "Turnover" if kind == "STEAL" else "Missed Shot"
        )
        assert secondary["personId"] != primary[0]["personId"]
        assert secondary["teamId"] != primary[0]["teamId"]
        secondary_counts[kind] += 1
    assert secondary_counts == expected_secondary


def test_same_game_event_alignment_and_final_score():
    old_rows, new_rows = v2_rows(), actions("0021900001")
    assert len(old_rows) == 573
    assert len(new_rows) == 596
    assert {row["EVENTNUM"] for row in old_rows} == {
        row["actionNumber"] for row in new_rows
    }
    old_score = next(row["SCORE"] for row in reversed(old_rows) if row["SCORE"])
    new_score = next(row for row in reversed(new_rows) if row["scoreHome"])
    assert (
        tuple(int(value.strip()) for value in old_score.split("-"))
        == (
            int(new_score["scoreAway"]),
            int(new_score["scoreHome"]),
        )
        == (122, 130)
    )


@pytest.mark.parametrize(
    "event_number, expected_description, secondary_player",
    [
        (25, "Anunoby 25' 3PT Jump Shot (3 PTS) (VanVleet 1 AST)", 1627832),
        (65, "SUB: Ibaka FOR Gasol", 201586),
    ],
)
def test_assister_and_incoming_substitute_are_text_only(
    event_number, expected_description, secondary_player
):
    old = next(row for row in v2_rows() if row["EVENTNUM"] == event_number)
    group = [
        row for row in actions("0021900001") if row["actionNumber"] == event_number
    ]
    assert len(group) == 1
    assert old["PLAYER2_ID"] == secondary_player
    assert group[0]["personId"] == old["PLAYER1_ID"]
    assert group[0]["personId"] != secondary_player
    assert group[0]["description"] == expected_description
    assert "assistPersonId" not in group[0]
    assert "incomingPersonId" not in group[0]


def test_offensive_foul_drawn_identity_is_not_in_v3_action():
    old = next(row for row in v2_rows() if row["EVENTNUM"] == 29)
    group = [row for row in actions("0021900001") if row["actionNumber"] == 29]
    assert len(group) == 1
    foul = group[0]
    assert old["PLAYER2_ID"] == 1627742  # Brandon Ingram, who drew the foul.
    assert foul["personId"] == old["PLAYER1_ID"] == 200768
    assert foul["description"] == "Lowry OFF.Foul (P1) (T.Brown)"
    assert "foulDrawnPersonId" not in foul
    assert not any(
        row["actionType"] == "Free Throw"
        and (row["period"], row["clock"]) == (foul["period"], foul["clock"])
        for row in actions("0021900001")
    )


def test_fractional_clock_crosses_existing_possession_count_threshold():
    old = next(row for row in v2_rows() if row["EVENTNUM"] == 184)
    new = next(row for row in actions("0021900001") if row["actionNumber"] == 184)
    assert old["PCTIMESTRING"] == "0:02"
    assert new["clock"] == "PT00M02.80S"
    assert Decimal(new["clock"][5:-1]) > 2
    assert Decimal(old["PCTIMESTRING"].split(":")[1]) == 2


def test_lane_violation_source_order_differs_from_v2_and_numeric_order():
    selected = {170, 171, 172}
    assert [row["EVENTNUM"] for row in v2_rows() if row["EVENTNUM"] in selected] == [
        170,
        171,
        172,
    ]
    assert [
        row["actionNumber"]
        for row in actions("0021900001")
        if row["actionNumber"] in selected
    ] == [170, 172, 171]


@pytest.mark.parametrize("game_id", FULL_GAMES)
def test_free_throw_outcomes_are_not_encoded_in_field_goal_flags(game_id):
    free_throws = [row for row in actions(game_id) if row["actionType"] == "Free Throw"]
    assert free_throws
    assert any(row["description"].startswith("MISS ") for row in free_throws)
    assert any(not row["description"].startswith("MISS ") for row in free_throws)
    assert all(row["isFieldGoal"] == 0 for row in free_throws)
    assert all(row["shotValue"] == 0 for row in free_throws)
    assert all(row["shotResult"] == "" for row in free_throws)


def test_team_heave_excerpt_has_intentional_team_only_attribution():
    rows = load_json("pbp/stats_v3_0042500317_heaves_excerpt.json")["game"]["actions"]
    heaves = [row for row in rows if row["actionType"] == "Heave"]
    assert [row["actionNumber"] for row in heaves] == [162, 541]
    for heave in heaves:
        assert heave["subType"] == "Team Field Goal Attempt"
        assert heave["personId"] == heave["teamId"] == 0
        assert heave["isFieldGoal"] == heave["shotValue"] == 0
        assert heave["shotResult"] == ""
        assert heave["location"] == "h"
        assert heave["description"] == "THUNDER Heave"
        preceding = rows[rows.index(heave) - 1]
        assert preceding["location"] == "h"
        assert preceding["teamId"] == 1610612760
    # This tests the recorded representation, not implemented FGA accounting.


def test_same_game_v3_coordinates_match_recorded_shot_charts():
    coordinates = {}
    for side in ("home", "away"):
        payload = load_json(f"game_details/stats_{side}_shots_0021900001.json")
        table = next(
            t for t in payload["resultSets"] if "GAME_EVENT_ID" in t["headers"]
        )
        for values in table["rowSet"]:
            row = dict(zip(table["headers"], values))
            coordinates[row["GAME_EVENT_ID"]] = (row["LOC_X"], row["LOC_Y"])
    shots = [row for row in actions("0021900001") if row["isFieldGoal"]]
    assert len(shots) == len(coordinates) == 205
    for shot in shots:
        assert (shot["xLegacy"], shot["yLegacy"]) == coordinates[shot["actionNumber"]]


def test_v2_comparison_game_baseline_is_offline_and_distinguishes_counted_possessions():
    source = StatsNbaPossessionFileLoader(str(DATA))
    with patch("requests.get", side_effect=AssertionError("Unexpected live request")):
        loader = StatsNbaPossessionLoader("0021900001", source)
        assert len(loader.items) == 227
        assert dict(loader.events[-1].score) == {
            1610612740: 122,
            1610612761: 130,
        }
        counted = {
            (row["team_id"], row["stat_key"]): row["stat_value"]
            for row in Possessions(loader.items).team_stats
            if row["stat_key"] in ("OffPoss", "DefPoss")
        }
        assert counted == {
            (1610612740, "OffPoss"): 112,
            (1610612740, "DefPoss"): 112,
            (1610612761, "OffPoss"): 112,
            (1610612761, "DefPoss"): 112,
        }
