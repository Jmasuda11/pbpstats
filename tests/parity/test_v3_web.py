"""Fetch, parse and save one game: context from the box score, JSON output."""

import json

import pytest
import responses

from pbpstats.data_loader.stats_nba_v3 import (
    V3DecodeError,
    V3EvidenceRequired,
    web,
)
from tools.parity import starter_cases
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, GAME, e, encode_v3, wrap

DATA = ROOT / "tests/parity/data/recorded_evidence"


def recorded(game_id):
    return (
        (DATA / "stats_v3_{}.json".format(game_id)).read_bytes(),
        (DATA / "stats_v3_boxscore_{}.json".format(game_id)).read_bytes(),
    )


def test_recorded_game_is_saved_with_every_source_row_once():
    pbp, box = recorded("0022500089")
    loader = web.load_game("0022500089", pbp, box, "recorded")
    data = json.loads(json.dumps(web.possessions_json(loader)))
    assert data["credited_possessions"] == {"1610612757": 103, "1610612750": 103}
    assert data["final_score"] == {"1610612757": 114, "1610612750": 118}
    assert data["supplied_period_starters"] == {}  # all inferred by the original
    rows = json.loads(pbp)["game"]["actions"]
    indices = sorted(
        i for p in data["possessions"] for x in p["events"] for i in x["source_indices"]
    )
    assert indices == list(range(len(rows)))
    for possession in data["possessions"]:
        teams = {str(possession["offense_team_id"]), str(possession["defense_team_id"])}
        assert set(possession["credited_lineups"]) == (
            teams if possession["counted"] else set()
        )


def test_reviewed_alias_resolves_a_name_the_box_score_lacks():
    pbp, box = recorded("0022500288")
    with pytest.raises(V3DecodeError, match="'Hansen' is unresolved"):
        web.load_game("0022500288", pbp, box, "recorded")
    loader = web.load_game(
        "0022500288", pbp, box, "recorded", aliases={1642905: ["Hansen"]}
    )
    assert loader.counts_by_team == {1610612757: 97, 1610612749: 96}
    with pytest.raises(V3DecodeError, match="not in the box score"):
        web.load_game("0022500288", pbp, box, "recorded", aliases={1: ["Nobody"]})


def test_starter_evidence_is_requested_exactly_and_recorded_when_fetched():
    case = next(
        c
        for c in starter_cases.catalog()
        if c["name"] == "starter_loader_boxscore_recovers_without_override"
    )
    raw, context = starter_cases.inputs(case)
    expected = case["responses"][1]
    with pytest.raises(V3EvidenceRequired) as needed:
        web.parse_possessions(raw, context)
    assert (needed.value.period, needed.value.params) == (1, expected["params"])
    assert needed.value.url == "https://stats.nba.com/stats/boxscoretraditionalv2"

    def fetch(period, url, params):
        return starter_cases.response(case["responses"][period], url, params)

    loader = web.parse_possessions(raw, context, fetch)
    recorded_requests = [
        d["request_params"]
        for d in loader.diagnostics
        if d["code"] == "recorded_starter_boxscore"
    ]
    assert recorded_requests == [expected["params"]]


def test_ambiguous_tip_falls_back_to_box_score_starters():
    # Two away players share the name in the description; only one starts.
    events = wrap(
        [
            e("jump", 720, HOME, 1, opponent=11, winner=12, winner_team=AWAY),
            e("make", 700, AWAY, 12),
        ]
    )
    rows = encode_v3(events)
    jump = next(r for r in rows if r["actionType"] == "Jump Ball")
    jump["description"] = jump["description"].replace("Tip to Player12", "Tip to Twin")
    pbp = json.dumps({"game": {"gameId": GAME, "actions": rows}}).encode()

    def player(identity, starter, family):
        return dict(
            personId=identity,
            firstName="",
            familyName=family,
            nameI="P. " + family,
            position="F" if starter else "",
        )

    def team(team_id, first, twin=None):
        players = [
            player(i, i < first + 5, "Player{}".format(i))
            for i in range(first, first + 8)
        ]
        if twin:
            for p in players:
                if p["personId"] in twin:
                    p["familyName"] = "Twin"
        return dict(teamId=team_id, players=players)

    box = json.dumps(
        {
            "boxScoreTraditional": dict(
                homeTeamId=HOME,
                awayTeamId=AWAY,
                homeTeam=team(HOME, 1),
                awayTeam=team(AWAY, 11, twin={12, 16}),
            )
        }
    ).encode()
    loader = web.load_game(GAME, pbp, box, "synthetic")
    tip = next(x for x in loader.events if x.event_num == jump["actionNumber"])
    assert tip.player2_id == 12  # the starter, not bench player 16
    assert loader.decoded.context.period_starters == {
        1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}
    }


@responses.activate
def test_fetch_and_save_writes_possessions_json(tmp_path):
    pbp, box = recorded("0022500089")
    responses.add(responses.GET, web.STATS_URL + "playbyplayv3", body=pbp)
    responses.add(responses.GET, web.STATS_URL + "boxscoretraditionalv3", body=box)
    output = tmp_path / "game.json"
    web.main(["0022500089", "-o", str(output)])
    first, second = (call.request for call in responses.calls)
    assert first.url.startswith(web.STATS_URL + "playbyplayv3?")
    assert "GameID=0022500089" in first.url and "StartPeriod=0" in first.url
    assert "boxscoretraditionalv3?" in second.url and "RangeType=0" in second.url
    assert first.headers["User-Agent"] == web.HEADERS["User-Agent"]
    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["possessions"]) == 208
    assert data["sources"]["pbp"]["sha256"] == web.hashlib.sha256(pbp).hexdigest()
