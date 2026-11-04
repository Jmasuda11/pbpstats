"""The league's live play-by-play names the fouled player V3 has no field for."""

from collections import Counter
import json

import pytest

import pbpstats
from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3DecodeError,
    V3FouledPlayerEvidence,
    V3JumpBallEvidence,
    web,
)
from pbpstats.data_loader.stats_nba_v3.decoder import DecodedV3
from pbpstats.resources.enhanced_pbp import Foul
from pbpstats.resources.possessions.possessions import Possessions
from tools.parity.reference import ROOT

DATA = ROOT / "tests/parity/data/recorded_evidence"
GAME = "0022500100"
PBP, BOX, LIVE = (
    (DATA / name.format(GAME)).read_bytes()
    for name in ("stats_v3_{}.json", "stats_v3_boxscore_{}.json", "live_{}.json")
)
CONTEXT = web.context_from_boxscore(GAME, PBP, BOX, "recorded")
# The game's first personal foul, and the same foul in the live feed.
FOUL = next(
    row
    for row in json.loads(PBP)["game"]["actions"]
    if (row["actionType"], row["subType"].strip()) == ("Foul", "Personal")
)
NUMBER, FOULER = FOUL["actionNumber"], FOUL["personId"]


def fouled_player(event):
    return getattr(event, "player3_id", None)


def live_with(change):
    payload = json.loads(LIVE)
    action = next(a for a in payload["game"]["actions"] if a["actionNumber"] == NUMBER)
    action.update(change)
    return json.dumps(payload).encode()


# The game's opening tip goes to a surname two players share, which the live feed decides.
JUMP_BALLS = V3JumpBallEvidence(LIVE, "recorded", CONTEXT.pbp_sha256)


def decoded(live):
    return DecodedV3(
        PBP,
        CONTEXT,
        JUMP_BALLS,
        fouled_players=V3FouledPlayerEvidence(live, "recorded", CONTEXT.pbp_sha256),
    )


def foul_drawn_unknowns(decoded_v3):
    return [
        u["event_num"] for u in decoded_v3.unknown_attribution if u["role"] == "foul_drawn"
    ]


def test_each_foul_takes_the_live_fouled_player_and_its_drawn_statistics():
    loader = web.load_game(GAME, PBP, BOX, "recorded", live=web.SavedResponse(LIVE, "recorded"))
    assert foul_drawn_unknowns(loader.decoded) == []
    actions = json.loads(LIVE)["game"]["actions"]
    named = {
        a["actionNumber"]: a["foulDrawnPersonId"]
        for a in actions
        if a["actionType"] == "foul" and a.get("foulDrawnPersonId")
    }
    fouls = [e for e in loader.events if isinstance(e, Foul) and e.event_num in named]
    assert len(fouls) == 51
    for foul in fouls:
        assert foul.player3_id == named[foul.event_num]
        drawn = [
            row
            for row in foul.event_stats
            if row["stat_key"].endswith(pbpstats.FOULS_DRAWN_TYPE_STRING)
        ]
        assert {row["player_id"] for row in drawn} == {foul.player3_id}
    in_possessions = [
        row
        for possession in loader.items
        for row in possession.possession_stats
        if row["stat_key"].endswith(pbpstats.FOULS_DRAWN_TYPE_STRING)
    ]
    assert {row["player_id"] for row in in_possessions} == set(named.values())


def test_a_live_response_read_only_for_a_jump_ball_gives_no_fouled_player():
    def fetch(url):
        return web.SavedResponse(LIVE, url)

    plain = web.load_game(GAME, PBP, BOX, "recorded", fetch_live=fetch)
    named = web.load_game(GAME, PBP, BOX, "recorded", live=web.SavedResponse(LIVE, "recorded"))
    assert len(foul_drawn_unknowns(plain.decoded)) == 51
    assert not any(fouled_player(e) for e in plain.events if isinstance(e, Foul))
    # The fouled player moves nothing the original's possessions decide.
    assert plain.base_stats == named.base_stats
    assert [[e.event_num for e in p.events] for p in plain.items] == [
        [e.event_num for e in p.events] for p in named.items
    ]


@pytest.mark.parametrize(
    "change",
    [
        dict(actionNumber=99999),
        dict(actionType="turnover"),
        dict(period=FOUL["period"] + 1),
        dict(personId=FOULER + 1),
        dict(foulDrawnPersonId=None),
        dict(foulDrawnPersonId=0),
        dict(foulDrawnPersonId="1"),
        dict(foulDrawnPersonId=1),  # no one on the roster
        dict(foulDrawnPersonId=FOULER),  # the fouler's own team
    ],
)
def test_a_live_foul_that_does_not_fit_leaves_that_foul_unknown(change):
    fits = decoded(LIVE)
    assert NUMBER not in foul_drawn_unknowns(fits)
    unfit = decoded(live_with(change))
    assert foul_drawn_unknowns(unfit) == [NUMBER]
    for before, after in zip(fits.projected, unfit.projected):
        if before["event_num"] == NUMBER:
            assert before["player3_id"] and after["player3_id"] is None
        else:
            assert before == after


def test_two_live_fouls_at_one_number_identify_neither():
    payload = json.loads(LIVE)
    actions = payload["game"]["actions"]
    actions.append(next(a for a in actions if a["actionNumber"] == NUMBER))
    assert foul_drawn_unknowns(decoded(json.dumps(payload).encode())) == [NUMBER]


def test_the_evidence_is_bound_to_its_game_and_play_by_play():
    payload = json.loads(LIVE)
    payload["game"]["gameId"] = "0022500101"
    for evidence, message in [
        (V3FouledPlayerEvidence(json.dumps(payload).encode(), "recorded", CONTEXT.pbp_sha256),
         "game identity"),
        (V3FouledPlayerEvidence(LIVE, "recorded", "0" * 64), "raw PBP hash"),
    ]:
        with pytest.raises(V3DecodeError, match=message):
            DecodedV3(PBP, CONTEXT, JUMP_BALLS, fouled_players=evidence)


def test_a_response_that_is_not_json_gives_no_fouled_players():
    # The live host serves 0021900777 and 0021900795 as Python text. The game parses
    # as with no live play-by-play, though a jump ball could not read it either.
    text = repr(json.loads(LIVE)).encode()
    result = decoded(text)
    assert len(foul_drawn_unknowns(result)) == 51
    assert result.live_input["sha256"] == web.hashlib.sha256(LIVE).hexdigest()
    with pytest.raises(V3DecodeError, match="Invalid recorded live"):
        DecodedV3(PBP, CONTEXT, V3JumpBallEvidence(text, "recorded", CONTEXT.pbp_sha256))


def loaded_with(live):
    return web.load_game(GAME, PBP, BOX, "recorded", live=web.SavedResponse(live, "recorded"))


def test_a_game_with_every_fouled_player_has_its_detailed_statistics():
    loader = loaded_with(LIVE)
    assert loader.capabilities["detailed_event_stats"] == "available"
    assert loader.event_stats == [s for e in loader.events for s in e.event_stats]
    totals = Possessions(loader.items).player_stats
    in_possessions = Counter()
    for possession in loader.items:
        for row in possession.possession_stats:
            in_possessions[row["player_id"], row["team_id"], row["stat_key"]] += row["stat_value"]
    assert any(row["stat_key"].endswith(pbpstats.FOULS_DRAWN_TYPE_STRING) for row in totals)
    for row in totals:
        # The aggregate rounds fractional seconds; every count is exact.
        if isinstance(row["stat_value"], int):
            assert in_possessions[row["player_id"], row["team_id"], row["stat_key"]] == row["stat_value"]


def assert_gated(loader):
    assert loader.capabilities["detailed_event_stats"] == "unavailable"
    with pytest.raises(V3DecodeError, match="attribution completeness"):
        loader.event_stats
    with pytest.raises(V3DecodeError, match="attribution completeness"):
        Possessions(loader.items).player_stats


def test_a_game_with_one_foul_without_its_fouled_player_stays_gated():
    assert_gated(loaded_with(live_with(dict(foulDrawnPersonId=None))))


def test_a_game_with_no_live_play_by_play_stays_gated():
    assert_gated(
        web.load_game(GAME, PBP, BOX, "recorded", fetch_live=lambda url: web.SavedResponse(LIVE, url))
    )


def test_a_game_whose_live_response_is_not_json_stays_gated():
    assert_gated(
        StatsNbaV3PossessionLoader.from_context(
            PBP,
            CONTEXT,
            jump_balls=JUMP_BALLS,
            fouled_players=V3FouledPlayerEvidence(
                repr(json.loads(LIVE)).encode(), "recorded", CONTEXT.pbp_sha256
            ),
        )
    )
