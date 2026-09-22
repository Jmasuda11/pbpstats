"""Recorded evidence and counterexamples for the bounded reliability contract."""

import hashlib
import json
import shutil
import socket
from dataclasses import replace
from pathlib import Path

import pytest
import test_stats_v3_lineups as synthetic
import test_stats_v3_possessions as plays
from v3_league_fixtures import DATA, classified, lineup_evidence

from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.game import V3GameLoadError, load_game
from pbpstats.data_loader.stats_nba_v3.jump_balls import V3JumpBallEvidence
from pbpstats.data_loader.stats_nba_v3.lineups import (
    StatsNbaV3LineupLoader,
    V3LineupEvidence,
)
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.data_loader.stats_nba_v3.preparation import _witnesses, prepare_game
from pbpstats.resources.period_clock import parse_period_clock

JUMPS = ["0022500340", "0022500001", "1022600001"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("reliability validation attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def encoded(value):
    return json.dumps(value).encode()


def jump_inputs(gid):
    return dict(
        jump_ball_evidence="jump-balls.evidence.json",
        jump_ball_live=f"pbp/live_{gid}.json",
    )


def sources(gid="1022600001"):
    box, _ = classified(gid)
    raw = StatsNbaV3PbpLoader(gid, StatsNbaV3PbpFileLoader(DATA / gid))
    review = json.loads((DATA / gid / "jump-balls.evidence.json").read_bytes())
    live = json.loads((DATA / gid / f"pbp/live_{gid}.json").read_bytes())
    return box.context, raw, review, live


def bind(ctx, raw, review, live):
    live_bytes = encoded(live)
    review["live_sha256"] = hashlib.sha256(live_bytes).hexdigest()
    return V3JumpBallEvidence(encoded(review), live_bytes).bind(raw, ctx)


@pytest.mark.parametrize("gid", JUMPS)
def test_team_jump_proof_preserves_native_bytes_without_inventing_recipient(gid):
    original = (DATA / gid / f"pbp/stats_v3_{gid}.json").read_bytes()
    game = load_game(gid, DATA / gid, snapshot_complete=True, **jump_inputs(gid))
    review = json.loads((DATA / gid / "jump-balls.evidence.json").read_bytes())
    event = next(
        e
        for e in game.possessions.events
        if e.facts.group.primary.order == review["jumps"][0]["source_index"]
    )
    recipient = event.facts.participants.participants["tip_recipient"]
    assert recipient.status == "team" and recipient.player_id is None
    assert event.team_id == recipient.team_id in game.boxscore.context.team_ids
    assert recipient.external_sha256 == game.inputs["jump_ball_evidence"].sha256
    assert not hasattr(event, "player2_id")
    assert event.facts.group.primary.description.strip() == ""
    assert game.pbp.source_bytes == original
    with pytest.raises(ValueError, match="tip_recipient"):
        event.facts.participants.require_player("tip_recipient")
    for key in ("jump_ball_evidence", "jump_ball_live"):
        assert (
            hashlib.sha256(Path(game.inputs[key].path).read_bytes()).hexdigest()
            == game.inputs[key].sha256
        )


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("actionNumber", -1, "identity"),
        ("period", True, "identity"),
        ("actionType", "turnover", "event kind"),
        ("clock", "PT06M33S", "clocks"),
        ("descriptor", "startperiod", "clocks"),
        ("jumpBallWonPersonId", True, "roster"),
        ("jumpBallLostPersonId", 999, "roster"),
        ("jumpBallWonPlayerName", "Unknown", "name conflicts"),
        ("personId", False, "team recovery"),
        ("possession", 0, "team recovery"),
        ("teamId", "1611661313", "team recovery"),
        ("jumpBallRecoveredName", "Player", "team recovery"),
        ("jumpBallRecoveredPersonId", 1631136, "team recovery"),
        ("jumpBallRecoverdPersonId", False, "team recovery"),
        ("personIdsFilter", [1631136], "team recovery"),
    ],
)
def test_conflicting_live_fields_fail_even_with_refreshed_hash(field, value, match):
    ctx, raw, review, live = sources()
    live["game"]["actions"][review["jumps"][0]["live_source_index"]][field] = value
    with pytest.raises(ValueError, match=match):
        bind(ctx, raw, review, live)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda r, live: r.update(schema_version=True), "schema"),
        (lambda r, live: r.update(game_id="0022500001"), "game IDs"),
        (lambda r, live: live["game"].update(gameId="0022500001"), "game IDs"),
        (lambda r, live: r.update(pbp_sha256="stale"), "native bytes"),
        (lambda r, live: r.update(source=" "), "provenance"),
        (lambda r, live: r["jumps"][0].update(source=""), "provenance"),
        (lambda r, live: r["jumps"][0].update(source_index=True), "indices"),
        (lambda r, live: r["jumps"][0].update(live_source_index=99999), "indices"),
        (lambda r, live: r["jumps"].append(r["jumps"][0]), "indices"),
        (lambda r, live: r["jumps"][0].update(clock_basis="tolerance"), "clock_basis"),
        (
            lambda r, live: live["game"]["actions"].append(live["game"]["actions"][34]),
            "ambiguous identity",
        ),
    ],
)
def test_bad_join_records_fail(mutation, match):
    ctx, raw, review, live = sources()
    mutation(review, live)
    with pytest.raises(ValueError, match=match):
        bind(ctx, raw, review, live)


def test_exact_bytes_roster_and_opposing_jumpers_are_required():
    ctx, raw, review, live = sources()
    with pytest.raises(ValueError, match="live_sha256"):
        V3JumpBallEvidence(encoded(review), encoded(live) + b"\n").bind(raw, ctx)
    with pytest.raises(ValueError, match="complete matching"):
        bind(replace(ctx, roster_complete=False), raw, review, live)
    jump = live["game"]["actions"][34]
    jump["jumpBallLostPersonId"] = jump["jumpBallWonPersonId"]
    with pytest.raises(ValueError, match="opposing teams"):
        bind(ctx, raw, review, live)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r, live: r["jumps"][0].update(clock_basis="exact"),
        lambda r, live: live["game"]["actions"][1].update(clock="PT11M53S"),
        lambda r, live: live["game"]["actions"][0].update(subType="end"),
        lambda r, live: live["game"]["actions"][0].update(period=True),
        lambda r, live: live["game"]["actions"][2].update(isFieldGoal=True),
        lambda r, live: live["game"]["actions"][2].update(actionNumber=999),
        lambda r, live: live["game"]["actions"][2].update(personId=999),
        lambda r, live: live["game"]["actions"][2].update(actionType="turnover"),
        lambda r, live: live["game"]["actions"][2].update(shotResult="Made"),
        lambda r, live: live["game"]["actions"][1].update(scoreHome="2"),
    ],
)
def test_opening_recovery_is_bounded_by_matching_start_and_next_shot(mutation):
    ctx, raw, review, live = sources("0022500340")
    mutation(review, live)
    with pytest.raises(ValueError, match="jump|opening"):
        bind(ctx, raw, review, live)


@pytest.mark.parametrize(
    "raw", [b'{"game":{},"game":{}}', b'{"game":NaN}', b"[]", b"\xff"]
)
def test_malformed_json_is_rejected(raw):
    with pytest.raises(ValueError):
        V3JumpBallEvidence(b"{}", raw)


def test_changed_review_provenance_invalidates_lineup_approval():
    gid = "1022600001"
    ctx, raw, review, _ = sources(gid)
    review["source"] += "; changed provenance"
    jumps = V3JumpBallEvidence(
        encoded(review), (DATA / gid / f"pbp/live_{gid}.json").read_bytes()
    )
    facts = StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(
            raw, ctx, snapshot_complete=True, jump_ball_evidence=jumps
        )
    )
    with pytest.raises(ValueError, match="fingerprint|snapshot_sha256"):
        StatsNbaV3LineupLoader(
            facts, V3LineupEvidence(encoded(lineup_evidence(gid)), "review")
        )


@pytest.mark.parametrize("api", [load_game, prepare_game])
@pytest.mark.parametrize("field", ["jump_ball_evidence", "jump_ball_live"])
def test_both_jump_paths_required_before_reading_files(api, field, tmp_path):
    kwargs = {field: "missing.json"}
    if api is prepare_game:
        kwargs["substitution_stream_source"] = "Reviewed stream"
    with pytest.raises(V3GameLoadError, match="supplied together") as caught:
        api("1022600001", tmp_path, snapshot_complete=True, **kwargs)
    assert caught.value.diagnostic.stage == "configuration"


def test_missing_live_file_reports_evidence_stage(tmp_path):
    with pytest.raises(V3GameLoadError) as caught:
        load_game(
            "1022600001",
            DATA / "1022600001",
            snapshot_complete=True,
            jump_ball_evidence="jump-balls.evidence.json",
            jump_ball_live=tmp_path / "missing",
        )
    assert caught.value.diagnostic.stage == "jump_balls"
    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_relocation_and_stale_evidence_before_publication(tmp_path):
    gid = "1022600001"
    target = tmp_path / gid
    shutil.copytree(DATA / gid, target)
    game = load_game(gid, target, snapshot_complete=True, **jump_inputs(gid))
    assert len(game.possessions.events) == 448
    prepared = prepare_game(
        gid,
        target,
        snapshot_complete=True,
        substitution_stream_source="Reviewed final stream",
        review="lineups.evidence.json",
        **jump_inputs(gid),
    )
    assert prepared.ready, prepared.diagnostics
    path = target / f"pbp/live_{gid}.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="input changed"):
        prepared.write_lineups(tmp_path / "approved.json")
    assert not (tmp_path / "approved.json").exists()


def test_loose_ball_one_shot_award_still_blocks_publication(tmp_path):
    gid = "1022600061"
    prepared = prepare_game(
        gid,
        DATA / gid,
        snapshot_complete=True,
        substitution_stream_source="Reviewed final stream",
        review="lineups.review.json",
    )
    assert not prepared.ready
    assert any(
        "(297,)" in d.message and "compatible preceding foul" in d.message
        for d in prepared.diagnostics
    )
    with pytest.raises(ValueError, match="unresolved evidence"):
        prepared.write_lineups(tmp_path / "approved.json")


def test_two_misses_at_same_clock_do_not_share_a_shot_clock_placeholder():
    result = plays.load(
        [
            synthetic.start(),
            plays.miss(),
            plays.rebound("PT09M59S", 0, plays.HOME),
            plays.miss("PT09M59S"),
            plays.rebound("PT09M59S", 0, plays.HOME),
            plays.turnover("PT09M59S", subtype="Shot Clock Turnover"),
            synthetic.end(),
        ]
    )
    assert result.events[2].is_real_rebound and result.events[2].oreb
    assert not result.events[4].is_real_rebound
    assert result.events[4].placeholder_reason == "shot_clock_turnover"


def test_hanging_technical_and_five_second_team_turnover():
    result = plays.load(
        [
            synthetic.start(),
            plays.foul("Hanging Technical"),
            plays.ft(category="Technical"),
            plays.turnover(pid=plays.HOME, subtype="5 Second Violation"),
            synthetic.end(),
        ]
    )
    foul, turnover = result.events[1], result.events[3]
    assert (
        foul.is_technical
        and not foul.counts_as_personal_foul
        and not foul.counts_towards_penalty
    )
    assert turnover.player1_id == 0 and not turnover.is_steal
    assert turnover.is_possession_ending_event


def ejection(pid=1):
    return synthetic.row(
        "Ejection", "Other", "PT10M00S", pid, plays.HOME, f"Player{pid} Ejection"
    )


def test_ejection_requires_explicit_replacement_and_is_not_starter_evidence():
    rows = [
        synthetic.start(),
        ejection(),
        synthetic.sub(1, 6),
        synthetic.shot(6),
        synthetic.end(),
    ]
    result = plays.load(rows, batches=[[2]])
    assert result.events[1].facts.kind == "ejection"
    assert 1 in result.events[1].lineup.before[plays.HOME]
    assert 6 in result.events[2].lineup.after[plays.HOME]
    assert 1 not in _witnesses(
        synthetic.events([synthetic.start(), ejection(), synthetic.end()]).items
    )


@pytest.mark.parametrize(
    "tail,match",
    [
        ([synthetic.shot(2)], "explicit replacement"),
        ([synthetic.shot(1)], "cannot participate"),
        ([ejection()], "already ejected"),
        ([synthetic.sub(1, 6), synthetic.sub(6, 1, "PT09M00S")], "re-enter"),
    ],
)
def test_ejected_player_cannot_continue_or_reenter(tail, match):
    facts = synthetic.events([synthetic.start(), ejection()] + tail + [synthetic.end()])
    batches = [[e.group.primary.order] for e in facts.items if e.kind == "substitution"]
    with pytest.raises(ValueError, match=match):
        synthetic.load(facts, synthetic.evidence(facts, batches=batches))


def test_new_live_captures_and_bench_identity_joins_are_independently_checkable():
    entries = json.loads((DATA / "manifest.json").read_bytes())["games"]
    assert sum("live_evidence" in e for e in entries) == 7
    for entry in entries:
        if "live_evidence" not in entry:
            continue
        gid, source = entry["game_id"], entry["live_evidence"]
        raw = (DATA / gid / source["file"]).read_bytes()
        assert (
            len(raw) == source["bytes"]
            and hashlib.sha256(raw).hexdigest() == source["sha256"]
        )
        live = json.loads(raw)["game"]
        assert live["gameId"] == gid
        if gid not in ("0042500317", "0022500166", "1022600061"):
            continue
        box, facts = classified(gid)
        for bench in box.context.bench_people:
            assert box.context.player(bench.person_id) is None
            native = next(
                e.group.primary
                for e in facts.items
                if e.group.primary.get("personId") == bench.person_id
            )
            matches = [
                a for a in live["actions"] if a["actionNumber"] == native.action_number
            ]
            assert len(matches) == 1
            observed = matches[0]
            assert (observed["personId"], observed["teamId"], observed["period"]) == (
                bench.person_id,
                bench.team_id,
                native.period,
            )
            assert (
                parse_period_clock(observed["clock"])[1]
                == native.seconds_remaining_exact
            )
            assert source["sha256"] in bench.source
            assert bench.person_id not in _witnesses(facts.items)


def test_quiet_overtime_starter_has_explicit_live_entrance_and_on_court_witness():
    gid, pid = "0022500001", 1628392
    live = json.loads((DATA / gid / f"pbp/live_{gid}.json").read_bytes())["game"][
        "actions"
    ]
    incoming, start, foul = (live[i] for i in [558, 560, 575])
    assert (incoming["actionType"], incoming["subType"], incoming["personId"]) == (
        "substitution",
        "in",
        pid,
    )
    assert (start["actionType"], start["subType"], start["period"]) == (
        "period",
        "start",
        5,
    )
    assert incoming["clock"] == start["clock"]
    assert foul["period"] == 5 and foul["foulDrawnPersonId"] == pid
    assert not any(
        a["actionType"] == "substitution" and a.get("personId") == pid
        for a in live[559:575]
    )
    assert pid in lineup_evidence(gid)["periods"][4]["home"]
