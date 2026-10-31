"""Recorded live play-by-play completes the jump balls V3 leaves undecided."""

import hashlib
import json

import pytest

from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3DecodeError,
    V3JumpBallEvidence,
    V3JumpBallEvidenceRequired,
    web,
)
from pbpstats.data_loader.stats_nba_v3.decoder import DecodedV3
from pbpstats.resources.enhanced_pbp.stats_nba_v3 import StatsNbaV3JumpBall
from tools.parity.reference import ROOT

DATA = ROOT / "tests/parity/data/recorded_evidence"
ORL, CHI, OKC, IND = 1610612753, 1610612741, 1610612760, 1610612754
CARTER, VUCEVIC, TYUS_JONES, BANCHERO = 1628976, 202696, 1626145, 1631094


def recorded(game_id):
    return tuple(
        (DATA / name.format(game_id)).read_bytes()
        for name in ("stats_v3_{}.json", "stats_v3_boxscore_{}.json", "live_{}.json")
    )


def live_from(live, change=None):
    """The recorded live response, optionally with one jump-ball action altered."""
    payload = json.loads(live)
    if change:
        action = next(a for a in payload["game"]["actions"] if a["actionNumber"] == 4)
        action.update(change)
    return json.dumps(payload).encode()


def saved(live):
    return lambda url: web.SavedResponse(live, url)


def decoded(game_id, live):
    pbp, box, _ = recorded(game_id)
    context = web.context_from_boxscore(game_id, pbp, box, "recorded")
    evidence = V3JumpBallEvidence(live, "recorded", context.pbp_sha256)
    return DecodedV3(pbp, context, evidence)


def test_tip_to_a_shared_surname_needs_and_uses_the_live_recipient():
    pbp, box, live = recorded("0022500100")
    # Q1 12:00 "Jump Ball Carter Jr. vs. Vucevic: Tip to Jones": Orlando's Tyus
    # Jones and Chicago's Tre Jones both start, so V3 and the lineups cannot decide.
    with pytest.raises(V3JumpBallEvidenceRequired, match="'Jones' is unresolved") as error:
        web.load_game("0022500100", pbp, box, "recorded")
    assert error.value.url == (
        "https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA/liveData/"
        "playbyplay/playbyplay_0022500100.json"
    )
    loader = web.load_game("0022500100", pbp, box, "recorded", fetch_live=saved(live))
    jump = next(e for e in loader.events if e.event_num == 4)
    assert isinstance(jump, StatsNbaV3JumpBall)
    assert (jump.player1_id, jump.player3_id, jump.player2_id) == (CARTER, VUCEVIC, TYUS_JONES)
    assert jump.team_id == ORL
    assert loader.counts_by_team == {ORL: 108, CHI: 107}
    codes = [d for d in loader.diagnostics if d["code"].startswith("recorded_live")]
    assert codes == [
        dict(code="recorded_live_input", source=error.value.url,
             sha256=hashlib.sha256(live).hexdigest(),
             pbp_sha256=hashlib.sha256(pbp).hexdigest()),
        dict(code="recorded_live_jump_ball", event_num=4, jumpers=[CARTER, VUCEVIC],
             recipient=TYUS_JONES, team_recovery=False,
             basis="live action number, period and V3 jumper personId"),
    ]


def test_team_won_jump_ball_takes_the_opposing_jumper_and_team_from_live():
    # Q3 6:50: V3's description is blank; live records "Jump Ball I. Hartenstein
    # vs. S. Adams: Tip to Team (OKC)" with no recovering player.
    pbp, box, live = recorded("0022500001")
    context = web.context_from_boxscore("0022500001", pbp, box, "recorded")
    with pytest.raises(V3JumpBallEvidenceRequired, match="explicit resolvable"):
        DecodedV3(pbp, context)
    result = decoded("0022500001", live)
    row = next(r for r in result.projected if r["event_num"] == 424)
    assert (row["player1_id"], row["player3_id"]) == (1628392, 203500)
    assert (row["team_id"], row["player2_id"]) == (OKC, None)
    jump = StatsNbaV3JumpBall(row, 0)
    assert jump.team_id == OKC and not hasattr(jump, "player2_id")
    assert [d["event_num"] for d in result.recorded_jump_balls] == [424]
    assert result.recorded_jump_balls[0]["team_recovery"] is True


def team_recovery_2026_27(change=None):
    """0022600095 Q4 2:56: live records "Jump Ball P. Siakam vs. Z. Risacher: Tip
    to Team (IND)" in the 2026-27 form, descriptor "team" and no personId."""
    _, _, live = recorded("0022600095")
    payload = json.loads(live)
    action = next(a for a in payload["game"]["actions"] if a["actionNumber"] == 744)
    assert action["descriptor"] == "team" and "personId" not in action
    action.update(change or {})
    return json.dumps(payload).encode()


def test_2026_27_live_team_recovery_without_a_person_is_a_team_recovery():
    result = decoded("0022600095", team_recovery_2026_27())
    row = next(r for r in result.projected if r["event_num"] == 744)
    assert (row["player1_id"], row["player3_id"]) == (1627783, 1642258)
    assert (row["team_id"], row["player2_id"]) == (IND, None)
    assert result.recorded_jump_balls == [dict(
        code="recorded_live_jump_ball", event_num=744, jumpers=[1627783, 1642258],
        recipient=IND, team_recovery=True,
        basis="live action number, period and V3 jumper personId",
        live_format="2026-27 team recovery",
    )]


@pytest.mark.parametrize("change", [
    dict(jumpBallRecoveredName="Team (DAL)"),
    dict(descriptor="heldball"),
    dict(jumpBallRecoverdPersonId=1627783),
], ids=["names_another_team", "other_descriptor", "names_a_player"])
def test_2026_27_live_team_recovery_must_say_so(change):
    with pytest.raises(V3DecodeError):
        decoded("0022600095", team_recovery_2026_27(change))


@pytest.mark.parametrize("change, message", [
    (dict(jumpBallWonPersonId=BANCHERO), "jumpers disagree"),
    (dict(jumpBallLostPersonId=BANCHERO), "opposing jumper disagrees"),
    (dict(jumpBallRecoverdPersonId=BANCHERO), "tip recipient disagrees"),
    (dict(jumpBallRecoverdPersonId=None, personId=0), "team recovery is not explicit"),
    (dict(period=2), "lacks this jump ball"),
    (dict(actionNumber=9999), "lacks this jump ball"),
    (dict(jumpBallLostPersonId=None), "lacks this jump ball"),
])
def test_live_facts_that_contradict_or_miss_v3_are_rejected(change, message):
    _, _, live = recorded("0022500100")
    with pytest.raises(V3DecodeError, match=message) as error:
        decoded("0022500100", live_from(live, change))
    assert not isinstance(error.value, V3JumpBallEvidenceRequired)


def test_evidence_is_bound_to_its_game_and_play_by_play():
    pbp, box, live = recorded("0022500100")
    context = web.context_from_boxscore("0022500100", pbp, box, "recorded")
    payload = json.loads(live)
    payload["game"]["gameId"] = "0022500101"
    for evidence, message in [
        (V3JumpBallEvidence(json.dumps(payload).encode(), "recorded", context.pbp_sha256),
         "game identity"),
        (V3JumpBallEvidence(live, "recorded", "0" * 64), "raw PBP hash"),
        (V3JumpBallEvidence(live, " ", context.pbp_sha256), "provenance"),
        (V3JumpBallEvidence(b"not json", "recorded", context.pbp_sha256), "Invalid recorded live"),
    ]:
        with pytest.raises(V3DecodeError, match=message):
            DecodedV3(pbp, context, evidence)


def test_live_evidence_is_never_read_where_v3_decides():
    pbp = (DATA / "stats_v3_0022500089.json").read_bytes()
    box = (DATA / "stats_v3_boxscore_0022500089.json").read_bytes()
    context = web.context_from_boxscore("0022500089", pbp, box, "recorded")
    plain = web.parse_possessions(pbp, context)
    empty = json.dumps({"game": {"gameId": "0022500089", "actions": []}}).encode()
    supplied = StatsNbaV3PossessionLoader(
        pbp, context, jump_balls=V3JumpBallEvidence(empty, "recorded", context.pbp_sha256)
    )

    def shape(loader):
        return [(p.offense_team_id, [e.event_num for e in p.events]) for p in loader.items]

    assert shape(supplied) == shape(plain)
    assert supplied.base_stats == plain.base_stats
    assert [d for d in supplied.diagnostics if d["code"] != "recorded_live_input"] == (
        plain.diagnostics
    )


def test_save_game_records_the_live_response(tmp_path):
    pbp, box, live = recorded("0022500100")
    raw = dict(pbp=pbp, boxscore=box, pbp_url="pbp", boxscore_url="box", live=live,
               live_url="https://example.invalid/live.json")
    output = tmp_path / "game.json"
    web.save_game("0022500100", output, raw=raw, responses=tmp_path / "raw")
    data = json.loads(output.read_bytes())
    assert data["sources"]["live_play_by_play"] == dict(
        url="https://example.invalid/live.json", sha256=hashlib.sha256(live).hexdigest()
    )
    assert (tmp_path / "raw/playbyplay_live.json").read_bytes() == live
    del raw["live"]
    with pytest.raises(V3JumpBallEvidenceRequired):
        web.save_game("0022500100", tmp_path / "other.json", raw=raw)
