"""Full-game checks against separately observed NBA.com roster/box-score facts."""

import hashlib
import json
import socket
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal

import pytest
from v3_context_fixture import DATA, recorded_boxscore

from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.lineups import (
    StatsNbaV3LineupLoader,
    V3LineupEvidence,
)
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Recorded lineup loading attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def recorded():
    box = recorded_boxscore()
    raw = StatsNbaV3PbpLoader(box.game_id, StatsNbaV3PbpFileLoader(DATA))
    events = StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(
            raw, box.require_complete_roster(), snapshot_complete=True
        )
    )
    evidence = V3LineupEvidence.from_file(DATA / "v3/lineups_0021900001.evidence.json")
    return events, evidence


def test_page_projection_keeps_every_active_player_and_binds_source_bytes():
    box = recorded_boxscore()
    original = (DATA / box.evidence["derived_from"]["path"]).read_bytes()
    assert (
        hashlib.sha256(original).hexdigest() == box.evidence["derived_from"]["sha256"]
    )
    page = json.loads(original)
    assert page["kind"] == "reviewed_dom_observation"
    assert page["filters"] == ["Traditional", "All Periods"]
    assert len(box.context.players) == 26
    for side in ("home", "away"):
        team = box.source_data["boxScoreTraditional"][side + "Team"]
        assert team["teamId"] == page[side]["team_id"]
        projected = [
            [
                p["personId"],
                p["firstName"] + " " + p["familyName"],
                p["position"],
                p["statistics"]["minutes"],
                p["statistics"]["points"],
            ]
            for p in team["players"]
        ]
        assert projected == page[side]["players"]
    # Real DNPs absent from PBP actors now belong to the validated active pool.
    assert box.context.player(1629637).name == "Jaxson Hayes"
    assert box.context.player(1629744).name == "Matt Thomas"


def test_each_period_has_five_required_players_before_their_first_entrance(recorded):
    events, evidence = recorded
    page = json.loads((DATA / "v3/nba_page_0021900001.json").read_bytes())
    for period in evidence.data["periods"]:
        seen, required = set(), set()
        for event in events.items:
            if event.group.primary.period != period["period"]:
                continue
            if event.kind in ("period_start", "period_end", "timeout", "replay"):
                continue
            if event.subtype == "Technical" or (
                event.free_throw and event.free_throw.category == "technical"
            ):
                continue
            for role, participant in event.participants.participants.items():
                pid = participant.player_id
                if pid is None or pid in seen:
                    continue
                seen.add(pid)
                if role == "incoming":
                    continue
                required.add(pid)
                assert period["witnesses"][str(pid)] == {
                    "source_index": event.group.primary.order,
                    "role": role,
                    "description": event.group.primary.description,
                }
        assert required == set(period["home"] + period["away"])
        assert len(period["home"]) == len(period["away"]) == 5
        assert set(map(int, period["witnesses"])) == required
    for side in ("home", "away"):
        opening = sorted(p[0] for p in page[side]["players"] if p[2])
        assert evidence.data["periods"][0][side] == opening


def test_full_game_lineups_reconcile_independent_minutes_and_player_scoring(recorded):
    events, evidence = recorded
    result = StatsNbaV3LineupLoader(events, evidence)
    minutes, points = defaultdict(Decimal), Counter()
    batches = set()
    for item in result.items:
        event = item.event
        clock = event.group.primary.seconds_remaining_exact
        if event.kind == "period_start":
            previous = clock
        elapsed = previous - clock
        assert elapsed >= 0
        for players in item.before.values():
            assert len(set(players)) == 5
            for pid in players:
                minutes[pid] += elapsed
        previous = clock
        if event.recorded_points:
            points[event.participants.require_player("actor")] += event.recorded_points
        if item.batch_source_indices:
            batches.add(item.batch_source_indices)
    assert len(result.items) == 573
    assert len(batches) == 31 and sum(map(len, batches)) == 49
    page = json.loads((DATA / "v3/nba_page_0021900001.json").read_bytes())
    for side in ("home", "away"):
        players = page[side]["players"]
        assert sum(minutes[p[0]] for p in players) == 5 * (4 * 720 + 300)
        assert sum(points[p[0]] for p in players) == page[side]["points"]
        for pid, name, position, display, pts in players:
            if display.startswith("DNP"):
                assert minutes[pid] == points[pid] == 0
            else:
                # Retain NBA's 44:60/25:60 display in the fixture; arithmetic
                # carries the 60 seconds here, without altering source text.
                m, s = map(int, display.split(":"))
                assert abs(minutes[pid] - (60 * m + s)) <= Decimal("0.5"), name
                assert points[pid] == pts


def test_opening_markers_cannot_be_reused_for_the_second_quarter(recorded):
    events, evidence = recorded
    data = deepcopy(evidence.data)
    data["periods"][1]["home"] = data["periods"][0]["home"]
    data["periods"][1]["away"] = data["periods"][0]["away"]
    with pytest.raises(ValueError, match="not on court|outgoing player absent"):
        StatsNbaV3LineupLoader(
            events, V3LineupEvidence(json.dumps(data).encode(), "incorrect starters")
        )
