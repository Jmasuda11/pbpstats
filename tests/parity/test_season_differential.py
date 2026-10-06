"""Full-game original-V2 versus V3 comparison on the paired 2024-25 season."""

from collections import Counter
import json
import subprocess
import sys

import pytest

from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader, V3Context
from pbpstats.data_loader.stats_nba_v3.decoder import clock_text
from tools.parity.paired_season import season
from tools.parity.reference import ROOT, digest, prepare_reference
from tools.parity.season_differential import (
    compare_game,
    floored,
    in_v2_order,
    masked_events,
    season_names,
    v2_payload,
    v3_context,
)


def test_v2_rule_round_trips_a_recorded_v2_response():
    raw = json.loads(
        (prepare_reference() / "tests/data/pbp/stats_0021900001.json").read_bytes()
    )
    table = raw["resultSets"][0]
    # Exported cells are text, with blanks for JSON null.
    exported = [
        {
            key: "" if value is None else str(value)
            for key, value in zip(table["headers"], row)
        }
        for row in table["rowSet"]
    ]
    for row in exported:
        row["GAME_ID"] = row["GAME_ID"].lstrip("0")
    rebuilt = v2_payload("0021900001", exported)["resultSets"][0]
    assert rebuilt["headers"] == table["headers"]
    assert rebuilt["rowSet"] == table["rowSet"]


def test_floor_projection_reproduces_every_recorded_v2_clock():
    v2, v3, _ = season()
    for game_id, actions in v3.items():
        clocks = {int(row["EVENTNUM"]): row["PCTIMESTRING"] for row in v2[game_id]}
        for action in floored(actions):
            if action["actionType"]:
                assert clock_text(action["clock"]) == clocks[action["actionNumber"]]


def test_v2_order_diagnostic_only_reorders_whole_action_groups():
    v2, v3, _ = season()
    for game_id in ("0022400001", "0022400019"):
        reordered = in_v2_order(v3[game_id], v2[game_id])
        assert Counter(json.dumps(a, sort_keys=True) for a in reordered) == Counter(
            json.dumps(a, sort_keys=True) for a in v3[game_id]
        )
        expected = list(dict.fromkeys(int(r["EVENTNUM"]) for r in v2[game_id]))
        assert [a["actionNumber"] for a in reordered if a["actionType"]] == expected
        numbers = [a["actionNumber"] for a in reordered]
        assert all(  # Secondary rows stay with their primary action.
            numbers.index(n) + numbers.count(n) - 1
            == len(numbers) - 1 - numbers[::-1].index(n)
            for n in set(numbers)
        )


def test_v3_context_binds_only_unique_same_team_season_names():
    _, v3, _ = season()
    actions = v3["0022400004"]
    index, names = season_names(v3)
    context = v3_context("0022400004", actions, (index, names))
    actors = {(a["personId"], a["teamId"]) for a in actions}
    bound = {
        (b["player_id"], b["team_id"]) for b in context["season_bound_substitutes"]
    }
    assert bound and all(
        b["name"] == "Bona" for b in context["season_bound_substitutes"]
    )
    for identity, facts in context["roster"].items():
        assert (int(identity), facts["team_id"]) in actors | bound
    # A second same-team "Bona" in the season makes the name unbindable.
    team = next(iter(bound))[1]
    index[team]["bona"].add(1)
    assert not v3_context("0022400004", actions, (index, names))[
        "season_bound_substitutes"
    ]


def test_order_repairs_record_each_period_starter_recovery_once():
    # V2's order for this game needs one original rebound-order repair, which
    # rebuilds the events and reruns starter inference.
    v2, v3, _ = season()
    game = "0022400002"
    actions = in_v2_order(floored(v3[game]), v2[game])
    facts = v3_context(game, actions, season_names(v3))
    source = json.dumps({"game": {"gameId": game, "actions": actions}}).encode()
    context = V3Context(
        game,
        tuple(facts["team_ids"]),
        {int(k): v for k, v in facts["roster"].items()},
        {},
        facts["source"],
        digest(source),
    )
    diagnostics = StatsNbaV3PossessionLoader(source, context).diagnostics
    assert [d["code"] for d in diagnostics].count("legacy_order_repair") == 1
    periods = [d["period"] for d in diagnostics if d["code"] == "starter_recovery"]
    assert periods == [1, 2, 3, 4, 5]


def test_observation_failures_are_never_counted_as_rejections():
    loaded = dict(game_id="g", status="ok")
    broken = dict(
        game_id="g",
        status="observation_error",
        category="observation: KeyError",
        message="x",
    )
    assert compare_game(loaded, broken)["outcome"] == "observation_failed"
    assert compare_game(broken, loaded)["outcome"] == "observation_failed"


def test_fouled_player_mask_keeps_double_fouls_compared():
    def foul(number, code, player3):
        return dict(
            event_id=number,
            kind="StatsFoul",
            codes=[6, code],
            participants=dict(player3_id=player3),
        )

    old = dict(snapshot=dict(events=[foul(1, 1, 5), foul(2, 10, 7), foul(3, 16, 8)]))
    new = dict(
        snapshot=dict(events=[foul(1, 1, None), foul(2, 10, 7), foul(3, 16, None)])
    )
    for events in masked_events(old, new):
        assert [e["participants"]["player3_id"] for e in events] == ["n/a", 7, "n/a"]


@pytest.fixture(scope="module")
def compared(tmp_path_factory):
    output = tmp_path_factory.mktemp("season") / "report.json"
    games = ("0022400001", "0022400002", "0022400006")
    command = [sys.executable, "-B", "-m", "tools.parity.season_differential"]
    for game in games:
        command += ["--game", game]
    subprocess.run(
        command + ["--output", str(output)], cwd=str(ROOT), check=True, timeout=600
    )
    return json.loads(output.read_bytes())


def test_equivalent_facts_reproduce_the_original_exactly(compared):
    rows = compared["modes"]["floor_v2_order"]["games"]
    assert [r["outcome"] for r in rows] == ["identical"] * 3
    assert all(r["fouls_drawn_gap"] for r in rows)


def test_feed_order_alone_moves_free_throw_substitutions_between_possessions(compared):
    # V2 lists the 0:26.3 substitution (event 173) after both free throws; V3
    # lists it between them, so it joins the shooting team's possession.
    row = compared["modes"]["floor"]["games"][0]
    assert row["game_id"] == "0022400001"
    assert row["outcome"] == "different_decisions"
    assert row["decision_differences"] == {
        "possessions": {"path": "$[48].events.length", "expected": 3, "actual": 4},
        "events": {
            "path": "$.173.offense",
            "expected": 1610612738,
            "actual": 1610612737,
        },
    }
