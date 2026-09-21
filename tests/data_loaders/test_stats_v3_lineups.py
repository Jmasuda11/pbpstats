import json
import socket
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.context import V3GameContext, V3RosterPlayer
from pbpstats.data_loader.stats_nba_v3.lineups import (
    StatsNbaV3LineupLoader,
    V3LineupEvidence,
    lineup_fingerprints,
)
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import StatsNbaV3PbpLoader
from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData

GAME = "0021900001"
HOME, AWAY = 1610612761, 1610612740


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("lineup reconstruction attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def context():
    return V3GameContext(
        GAME,
        HOME,
        AWAY,
        tuple(
            V3RosterPlayer(pid, team, (f"Player{pid}",))
            for team, ids in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
            for pid in ids
        ),
        True,
        "Synthetic complete player pool, independent of synthetic PBP actors",
    )


def row(kind, subtype, clock, pid=0, team=0, description="", period=1, **extra):
    result = dict(
        actionType=kind,
        subType=subtype,
        period=period,
        clock=clock,
        personId=pid,
        teamId=team,
        location="h" if team == HOME else "v" if team == AWAY else "",
        description=description,
        shotValue=0,
        shotResult="",
        isFieldGoal=0,
    )
    result.update(extra)
    return result


def start(period=1):
    return row(
        "period", "start", "PT12M00S" if period <= 4 else "PT05M00S", period=period
    )


def end(period=1):
    return row("period", "end", "PT00M00S", period=period)


def sub(outgoing, incoming, clock="PT10M00S", team=HOME, period=1):
    return row(
        "Substitution",
        "",
        clock,
        outgoing,
        team,
        f"SUB: Player{incoming} FOR Player{outgoing}",
        period,
    )


def shot(pid, clock="PT09M00S", team=HOME, period=1, **extra):
    return row(
        "Made Shot",
        "Jump Shot",
        clock,
        pid,
        team,
        f"Player{pid} Jump Shot (2 PTS)",
        period,
        isFieldGoal=1,
        shotValue=2,
        shotResult="Made",
        **extra,
    )


def events(rows, ctx=None, complete=True):
    rows = [dict(r, actionId=i + 1, actionNumber=i + 1) for i, r in enumerate(rows)]
    raw = StatsNbaV3PbpLoader(
        GAME,
        SimpleNamespace(
            load_data=lambda _: V3PbpSourceData(
                {"game": {"gameId": GAME, "actions": rows}}
            )
        ),
    )
    return StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(raw, ctx or context(), snapshot_complete=complete)
    )


def period_evidence(period=1, home=None, away=None):
    return dict(
        period=period,
        home=home or [1, 2, 3, 4, 5],
        away=away or [11, 12, 13, 14, 15],
        source=f"Synthetic independently specified period {period} starters",
    )


def evidence(loader, periods=None, batches=None):
    return dict(
        schema_version=1,
        game_id=GAME,
        **lineup_fingerprints(loader),
        periods=periods if periods is not None else [period_evidence()],
        batches=[
            dict(source_indices=indices, source="Synthetic reviewed substitution batch")
            for indices in (batches or [])
        ],
    )


def load(loader, data):
    return StatsNbaV3LineupLoader(
        loader, V3LineupEvidence(json.dumps(data).encode(), "synthetic-lineups.json")
    )


def test_batch_is_atomic_and_input_order_is_preserved():
    loader = events(
        [start(), sub(1, 6), sub(2, 7), sub(11, 16, team=AWAY), shot(6), end()]
    )
    result = load(loader, evidence(loader, batches=[[1, 2, 3]]))
    assert [x.event for x in result.items] == list(loader.items)
    for transition in result.items[1:4]:
        assert transition.before[HOME] == (1, 2, 3, 4, 5)
        assert transition.after[HOME] == (3, 4, 5, 6, 7)
        assert transition.before[AWAY] == (11, 12, 13, 14, 15)
        assert transition.after[AWAY] == (12, 13, 14, 15, 16)
        assert transition.batch_source_indices == (1, 2, 3)
    assert result.items[4].before == result.items[3].after
    with pytest.raises(TypeError):
        result.items[1].after[HOME] = (1,)


def test_synthetic_four_quarters_and_overtime_need_separate_starters():
    rows, periods, batches = [], [], []
    for period in range(1, 6):
        home = [1, 2, 3, 4, 5] if period % 2 else [2, 3, 4, 5, 6]
        periods.append(period_evidence(period, home=home))
        rows.append(start(period))
        batches.append([len(rows)])
        rows.append(sub(home[0], 7, clock="PT04M00S", period=period))
        rows.append(shot(7, clock="PT02M00S", period=period))
        rows.append(end(period))
    loader = events(rows)
    result = load(loader, evidence(loader, periods, batches))
    assert len(result.items) == 20
    for offset, period in enumerate(periods):
        assert set(result.items[offset * 4].before[HOME]) == set(period["home"])
        assert 7 in result.items[offset * 4 + 2].before[HOME]
    assert all(len(x.after[t]) == 5 for x in result.items for t in (HOME, AWAY))
    missing = evidence(loader, periods[:-1], batches)
    with pytest.raises(ValueError, match="missing period starters.*5"):
        load(loader, missing)


def test_equal_clock_batches_stay_separate_when_evidence_says_so():
    loader = events([start(), sub(1, 6), sub(6, 7), end()])
    result = load(loader, evidence(loader, batches=[[1], [2]]))
    assert 6 in result.items[1].after[HOME]
    assert 6 in result.items[2].before[HOME]
    assert 7 in result.items[2].after[HOME]
    with pytest.raises(ValueError, match="outgoing player absent"):
        load(loader, evidence(loader, batches=[[1, 2]]))


@pytest.mark.parametrize(
    "rows,batches,match",
    [
        ([start(), sub(8, 6), end()], [[1]], "outgoing player absent"),
        ([start(), sub(1, 2), end()], [[1]], "incoming player already"),
        ([start(), sub(1, 6), sub(1, 7), end()], [[1, 2]], "duplicate outgoing"),
        (
            [start(), sub(1, 6), sub(2, 6), end()],
            [[1, 2]],
            "duplicate outgoing or incoming",
        ),
        ([start(), sub(1, 6), end()], [], "missing substitution batch"),
        ([start(), sub(1, 6), end()], [[1], [1]], "repeated"),
        ([start(), sub(1, 6), end()], [[1, 1]], "repeated"),
        ([start(), sub(1, 6), sub(2, 7), end()], [[2, 1]], "source order"),
        (
            [
                start(),
                sub(1, 6),
                row("Timeout", "Regular", "PT10M00S"),
                sub(2, 7),
                end(),
            ],
            [[1, 3]],
            "contiguous",
        ),
        (
            [start(), sub(1, 6), shot(2, "PT10M00S"), sub(2, 7), end()],
            [[1, 3]],
            "contiguous",
        ),
        ([start(), sub(1, 6), sub(2, 7, "PT09M59S"), end()], [[1, 2]], "exact clock"),
        (
            [
                start(),
                sub(1, 6, "PT00M02.80000000000000002S"),
                sub(2, 7, "PT00M02.80000000000000001S"),
                end(),
            ],
            [[1, 2]],
            "exact clock",
        ),
        ([start(), shot(1), end()], [[1]], "non-substitution"),
    ],
)
def test_invalid_substitution_evidence_fails(rows, batches, match):
    loader = events(rows)
    with pytest.raises(ValueError, match=match) as error:
        load(loader, evidence(loader, batches=batches))
    assert GAME in str(error.value)
    assert "synthetic-lineups.json" in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        [1, 2, 3, 4, 4],
        [1, 2, 3, 4],
        [1, 2, 3, 4, 11],
        [1, 2, 3, 4, 999],
        [True, 2, 3, 4, 5],
    ],
)
def test_starter_sets_require_five_eligible_distinct_players(value):
    loader = events([start(), end()])
    data = evidence(loader)
    data["periods"][0]["home"] = value
    with pytest.raises(ValueError, match="five distinct|conflicts with roster"):
        load(loader, data)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("period", True, "period"),
        ("period", 2, "period"),
        ("source", "", "provenance"),
    ],
)
def test_starter_provenance_is_required(field, value, match):
    loader = events([start(), end()])
    data = evidence(loader)
    data["periods"][0][field] = value
    with pytest.raises(ValueError, match=match):
        load(loader, data)


@pytest.mark.parametrize(
    "rows,match",
    [
        ([shot(1), end()], "outside a started period"),
        ([start(), shot(1)], "complete period boundaries"),
        ([start(), start(), end()], "period boundary"),
        ([start(), end(), start(3), end(3)], "period boundary"),
        ([start(), shot(1, "PT08M00S"), shot(2, "PT09M00S"), end()], "clock increases"),
        ([dict(start(), clock="PT11M59S"), end()], "opening clock"),
        ([start(), dict(end(), clock="PT00M01S")], "at zero"),
    ],
)
def test_missing_boundaries_and_order_changes_are_not_repaired(rows, match):
    loader = events(rows)
    with pytest.raises(ValueError, match=match):
        load(loader, evidence(loader))


def test_missing_roster_and_snapshot_completeness_fail():
    for loader in (
        events([start(), end()], complete=False),
        events([start(), end()], ctx=replace(context(), roster_complete=False)),
    ):
        with pytest.raises(ValueError, match="complete roster and snapshot"):
            load(loader, evidence(loader))


def test_unknown_substitute_never_leaves_the_lineup_unchanged():
    loader = events([start(), sub(1, 99), end()])
    with pytest.raises(ValueError, match="incoming is unresolved"):
        load(loader, evidence(loader, batches=[[1]]))


def test_known_off_court_actor_and_secondary_participant_fail():
    for event in (
        shot(8),
        dict(shot(1), description="Player1 Jump Shot (2 PTS) (Player8 1 AST)"),
    ):
        loader = events([start(), event, end()])
        with pytest.raises(ValueError, match="not on court"):
            load(loader, evidence(loader))


def test_technical_foul_on_bench_player_does_not_change_lineup():
    technical = row("Foul", "Technical", "PT10M00S", 8, HOME, "Player8 T.FOUL")
    loader = events([start(), technical, end()])
    result = load(loader, evidence(loader))
    assert result.items[1].before == result.items[1].after
    assert 8 not in result.items[1].after[HOME]


def test_snapshot_and_roster_fingerprints_reject_stale_evidence():
    loader = events([start(), shot(1), end()])
    data = evidence(loader)
    changed_event = events([start(), shot(2), end()])
    with pytest.raises(ValueError, match="snapshot_sha256"):
        load(changed_event, data)
    changed_roster = events(
        [start(), shot(1), end()], ctx=replace(context(), roster_source="Other source")
    )
    with pytest.raises(ValueError, match="context_sha256"):
        load(changed_roster, data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("game_id", "0022400001"),
        ("periods", {}),
        ("batches", {}),
    ],
)
def test_bad_envelope_fails(field, value):
    loader = events([start(), end()])
    data = evidence(loader)
    data[field] = value
    with pytest.raises(ValueError, match=field):
        load(loader, data)


def test_evidence_file_is_offline_and_defensive(tmp_path):
    loader = events([start(), end()])
    raw = json.dumps(evidence(loader)).encode()
    path = tmp_path / "lineups.json"
    with pytest.raises(FileNotFoundError):
        V3LineupEvidence.from_file(path)
    path.write_bytes(raw)
    record = V3LineupEvidence.from_file(path)
    record.data["periods"][0]["home"].clear()
    assert len(StatsNbaV3LineupLoader(loader, record).items) == 2
    assert record.source_bytes == path.read_bytes() == raw


@pytest.mark.parametrize(
    "raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b"[]", b"\xff"]
)
def test_malformed_evidence_fails(raw):
    with pytest.raises(ValueError, match="Lineup evidence"):
        V3LineupEvidence(raw, "bad.json")
