"""The oracle comparison records each decision and names every difference."""

import copy
import json

import pytest

from tools.parity import native_differential as differential
from tools.parity.reference import ROOT, git

GAME = "0021900029"


def recorded_game():
    return dict(differential.recorded_games(differential.RECORDED)[GAME], aliases={})


@pytest.fixture(scope="module")
def record():
    observed = differential.observe(recorded_game())
    assert observed["status"] == "parsed"
    return observed


def events(record, family):
    return [e for e in record["events"].values() if family in e["families"]]


def test_a_game_is_observed_the_same_way_twice(record):
    again = differential.observe(recorded_game())
    assert differential.compare(GAME, record, again) == dict(game=GAME, outcome="identical")


def test_an_absent_participant_differs_from_a_recorded_one(record):
    unassisted = [e for e in events(record, "FieldGoal") if e["is_made"] and not e["is_assisted"]]
    assert unassisted and all(e["player2_id"] == "absent" for e in unassisted)
    substitutions = events(record, "Substitution")
    assert substitutions and all(type(e["player2_id"]) is int for e in substitutions)


def test_each_family_records_its_decisions(record):
    foul = events(record, "Foul")[0]
    assert type(foul["number_of_fta_for_foul"]) in (int, type(None))
    free_throw = events(record, "FreeThrow")[0]
    assert type(free_throw["foul_that_led_to_ft"]) is int  # an event, by number
    assert "is_made" not in events(record, "Timeout")[0]


def test_every_changed_field_is_named(record):
    changed = copy.deepcopy(record)
    number, shot = next(
        (k, e) for k, e in changed["events"].items() if "FieldGoal" in e["families"]
    )
    shot["is_and1"] = not shot["is_and1"]
    shot["player3_id"] = None
    changed["possessions"]["1:4"]["offense_team_id"] = 0
    row = differential.compare(GAME, record, changed)
    assert row["outcome"] == "differs"
    assert row["fields"] == [
        "$.events.*.is_and1",
        "$.events.*.player3_id",
        "$.possessions.*.offense_team_id",
    ]
    path = f"$.events.{number}.player3_id"
    assert dict(path=path, oracle="absent", candidate=None) in row["differences"]


def test_rejections_are_compared_in_full():
    old = dict(
        status="rejected",
        error="V3DecodeError",
        module="pbpstats.data_loader.stats_nba_v3.decoder",
        message="Unsupported rebound subtype",
    )
    assert differential.compare(GAME, old, dict(old))["outcome"] == "both_rejected"
    moved = dict(old, module="pbpstats.resources.enhanced_pbp.stats_nba_v3.rebound")
    assert differential.compare(GAME, old, moved)["fields"] == ["$.module"]


def write(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{}")


def test_both_layouts_are_discovered(tmp_path):
    game_id = "0022600001"
    for capture in ("20261001T000000Z-a", "20261002T000000Z-b"):
        bundle = tmp_path / "nba/2026" / game_id / capture / "bundle"
        write(bundle / f"pbp/stats_v3_{game_id}.json")
        write(bundle / f"game_details/stats_v3_boxscore_{game_id}.json")
    write(bundle / "starters/boxscoretraditionalv2_period_5.json")
    write(bundle / "starters/boxscoretraditionalv2_period_5.source.json")
    write(bundle / f"live/playbyplay_{game_id}.json")
    found = differential.bundle_games(tmp_path)[game_id]
    assert "20261002T000000Z-b" in found["pbp"]  # the last bundle is used
    assert list(found["starters"]) == ["5"] and found["live"]

    flat = tmp_path / "flat"
    write(flat / f"stats_v3_{game_id}.json")
    write(flat / f"stats_v3_boxscore_{game_id}.json")
    write(flat / f"stats_boxscoretraditionalv2_{game_id}_period_3.json")
    found = differential.recorded_games(flat)[game_id]
    assert list(found["starters"]) == ["3"] and found["live"] is None


def test_the_oracle_is_pinned_to_its_tree():
    manifest = json.loads((ROOT / "tests/parity/manifest.json").read_bytes())
    revision = manifest["oracle_revision"]
    assert git("rev-parse", revision + "^{tree}").decode().strip() == manifest["oracle_tree"]
    listed = git("ls-tree", "-r", "--name-only", revision, "pbpstats").decode().split()
    assert sorted(manifest["oracle_files"]) == sorted(listed)
