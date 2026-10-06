"""V3 decoding is independently checked before trusting shared decisions."""

from collections import defaultdict
from decimal import Decimal
import hashlib
import json

import pytest

from pbpstats.data_loader.stats_nba_v3 import (
    StatsNbaV3PossessionLoader,
    V3Context,
    V3DecodeError,
)
from pbpstats.data_loader.stats_nba_v3.decoder import DecodedV3
from pbpstats.data_loader.stats_nba_v3.possessions import TEAM_IDS_GUARD, V3Possession
from pbpstats.resources.possessions.possession import Possession
from pbpstats.resources.enhanced_pbp.stats_nba.enhanced_pbp_factory import (
    StatsNbaEnhancedPbpFactory,
)
from tools.parity.reference import ROOT, prepare_reference
from tools.parity.run import compare, worker
from tools.parity.scenarios import HOME, AWAY, GAME, catalog, e, encode_v3, wrap
from tools.parity.v3_cases import load_paired, load_synthetic, load_synthetic_rows


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket

    def blocked(*args, **kwargs):
        pytest.fail("Offline adapter tried to access the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def inputs(events=None):
    rows = encode_v3(events or wrap([e("make"), e("turnover", 580, AWAY, 11)]))
    payload = {"game": {"gameId": GAME, "actions": rows}}
    context = V3Context(
        GAME,
        (HOME, AWAY),
        {
            player: {"team_id": team, "names": ["Player{}".format(player)]}
            for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
            for player in players
        },
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Independent test evidence",
        "",
    )
    return payload, context


def decode(payload, context):
    source = json.dumps(payload).encode()
    context.pbp_sha256 = hashlib.sha256(source).hexdigest()
    return DecodedV3(source, context)


def test_all_independent_synthetic_sequences_match_original():
    original = worker(prepare_reference())
    candidate = worker(ROOT, provider="v3")
    result = compare(original, candidate)
    assert result["cases"] == 145
    assert result["statuses"] == {"same": 145}
    assert result["matching_credit_cases"] == 145


def test_original_event_classes_are_used_without_rule_overrides():
    loaded = load_synthetic(wrap([e("make"), e("turnover", 580, AWAY, 11)]))
    factory = StatsNbaEnhancedPbpFactory()
    for event in loaded.events:
        assert type(event) is factory.get_event_class(event.event_type)
    assert loaded.capabilities["full_game_validated"] is False
    with pytest.raises(V3DecodeError, match="attribution completeness"):
        loaded.event_stats


@pytest.mark.parametrize(
    "field,value",
    [
        ("shotValue", True),
        ("shotValue", 4),
        ("isFieldGoal", True),
        ("shotResult", "Missed"),
        ("personId", 999),
        ("teamId", AWAY),
        ("period", 0),
        ("clock", "PT00M60S"),
        ("clock", "PT-1M10S"),
        ("actionNumber", True),
        ("actionId", 1),
        ("description", "MISS Player1 Jump Shot"),
        ("actionType", "Unknown"),
        ("subType", "Unknown Shot"),
    ],
)
def test_conflicting_source_facts_are_rejected(field, value):
    payload, context = inputs()
    payload["game"]["actions"][1][field] = value
    with pytest.raises(V3DecodeError):
        decode(payload, context)


def test_blank_turnover_reason_is_the_recorded_v2_no_turnover_code():
    # The paired 2024-25 exports record V2 code 0 for this event; the original
    # treats code 0 as is_no_turnover, which does not end a possession.
    rows = encode_v3(wrap([e("make"), e("turnover", 580, AWAY, 11)]))
    turnover = next(row for row in rows if row["actionType"] == "Turnover")
    turnover["subType"] = ""
    loaded = load_synthetic_rows(rows)
    event = next(x for x in loaded.events if x.event_num == turnover["actionNumber"])
    assert event.event_action_type == 0
    assert event.is_no_turnover and not event.is_possession_ending_event


@pytest.mark.parametrize(
    "team", (0, AWAY), ids=("coach_without_team", "inactive_player")
)
def test_off_roster_technical_actor_keeps_its_recorded_team(team):
    # V2 records the same personId/teamId pair; a coach has no team in either
    # feed, and the original then treats the person ID as the event's team.
    rows = encode_v3(wrap([e("make"), e("foul", 590, AWAY, 11, subtype="Technical")]))
    foul = next(row for row in rows if row["actionType"] == "Foul")
    foul.update(personId=99, teamId=team, description="Coach Foul:T.FOUL")
    loaded = load_synthetic_rows(rows)
    event = next(x for x in loaded.events if x.event_num == foul["actionNumber"])
    assert (event.team_id, event.player1_id) == ((team, 99) if team else (99, 0))
    assert event.is_technical
    assert {d["code"] for d in loaded.diagnostics} == {"non_roster_actor"}


def double_foul_rows(description):
    rows = encode_v3(
        wrap([e("make"), e("foul", 590, HOME, 2, subtype="Double Personal")])
    )
    foul = next(row for row in rows if row["actionType"] == "Foul")
    foul["description"] = description
    return rows, foul


def test_double_foul_records_both_named_players_as_v2_does():
    rows, foul = double_foul_rows(
        " Foul : Double Personal - Player2 (1 PF), Player12 (1 PF) (A.Referee)"
    )
    loaded = load_synthetic_rows(rows)
    event = next(x for x in loaded.events if x.event_num == foul["actionNumber"])
    assert (event.player1_id, event.player3_id, event.is_double_foul) == (2, 12, True)
    credited = {(s["player_id"], s["stat_key"]) for s in event.event_stats}
    assert {(2, "Double Fouls"), (12, "Double Fouls")} <= credited


def test_double_technical_with_an_unidentified_coach_keeps_the_game():
    rows, foul = double_foul_rows("Double Technical - Player2, Coach (A.Referee)")
    foul["subType"] = "Double Technical"
    loaded = load_synthetic_rows(rows)
    event = next(x for x in loaded.events if x.event_num == foul["actionNumber"])
    assert event.is_double_technical and not hasattr(event, "player3_id")
    assert {
        "event_num": foul["actionNumber"],
        "role": "double_foul_opponent",
        "name": "Coach",
    } in loaded.decoded.unknown_attribution
    rows, _ = double_foul_rows(" Foul : Double Personal - Player2 (1 PF), Coach (1 PF)")
    with pytest.raises(V3DecodeError, match="unresolved"):
        load_synthetic_rows(rows)


def test_double_foul_description_must_name_its_actor_first():
    rows, _ = double_foul_rows(
        " Foul : Double Personal - Player3 (1 PF), Player12 (1 PF)"
    )
    with pytest.raises(V3DecodeError, match="both recorded participants"):
        load_synthetic_rows(rows)


def test_off_roster_actor_is_still_rejected_outside_technicals():
    payload, context = inputs(
        wrap([e("make"), e("foul", 590, AWAY, 11, subtype="Personal")])
    )
    payload["game"]["actions"][2]["personId"] = 99
    with pytest.raises(V3DecodeError, match="Actor missing from recorded roster"):
        decode(payload, context)


def test_lone_jump_ball_after_a_replay_review_gets_its_offense():
    # Same shape as 0022500861: made free throws, with a replay review in the
    # possession, then a lone jump ball whose offense needs both team IDs.
    rows = encode_v3(
        wrap(
            [
                e("make", 700, HOME, 1),
                e("foul", 680, HOME, 2, subtype="Shooting"),
                e("timeout", 680, AWAY, 0),
                e("replay", 680, 0, 0),
                e("ft", 680, AWAY, 11, attempt=1, total=2, made=True),
                e("ft", 680, AWAY, 11, attempt=2, total=2, made=True),
                e("jump", 660, HOME, 1, opponent=11, winner=12, winner_team=AWAY),
                e("make", 640, AWAY, 12),
            ]
        )
    )
    loaded = load_synthetic_rows(rows)
    jump = next(
        p
        for p in loaded.items
        if [type(x).__name__ for x in p.events] == ["StatsJumpBall"]
    )
    with pytest.raises(AttributeError, match="team_id"):
        Possession.get_team_ids(jump)  # the original method, same possessions
    assert jump.offense_team_id == HOME
    assert loaded.capabilities["defect_guards"] == [TEAM_IDS_GUARD]


def test_guarded_team_ids_equal_the_original_wherever_it_returns():
    games = [load_synthetic(case["events"]) for case in catalog()]
    games.append(load_paired(prepare_reference("prior") / "tests/data"))
    compared, raised = 0, []
    for game in games:
        teams = sorted({x.team_id for x in game.events if getattr(x, "team_id", 0)})
        for possession in game.items:
            try:
                expected = Possession.get_team_ids(possession)
            except AttributeError:
                raised.append((possession, teams))
                continue
            assert V3Possession.get_team_ids(possession) == expected
            compared += 1
    # Called directly, the original also raises on three possessions after a
    # replay; it decides their offense without this method, so no output
    # changes. Two are in the paired 2019 game.
    assert (compared, len(raised)) == (2441, 3)
    assert all(sorted(V3Possession.get_team_ids(p)) == t for p, t in raised)


def test_unknown_foul_drawn_is_recorded_only_where_v2_has_a_fouled_player():
    rows = encode_v3(
        wrap(
            [
                e("make"),
                e("foul", 590, AWAY, 11, subtype="Personal"),
                e("foul", 580, AWAY, 12, subtype="Technical"),
            ]
        )
    )
    personal, _ = [r["actionNumber"] for r in rows if r["actionType"] == "Foul"]
    loaded = load_synthetic_rows(rows)
    assert loaded.decoded.unknown_attribution == [
        {"event_num": personal, "role": "foul_drawn"}
    ]


def test_malformed_provenance_or_json_is_a_declared_rejection():
    payload, context = inputs()
    context.source = None
    with pytest.raises(V3DecodeError, match="provenance"):
        decode(payload, context)
    source = b"{not json"
    _, context = inputs()
    context.pbp_sha256 = hashlib.sha256(source).hexdigest()
    with pytest.raises(V3DecodeError, match="not valid JSON"):
        DecodedV3(source, context)


def test_roster_names_match_regardless_of_surrounding_whitespace():
    payload, context = inputs(
        wrap([e("sub", 600, HOME, 2, incoming=6), e("make", 590)])
    )
    context.roster[6]["names"] = [" Player6 "]
    projected = decode(payload, context).projected
    assert [r["PLAYER2_ID"] for r in projected if r["EVENTMSGTYPE"] == 8] == [6]


def test_unrecorded_turnover_reason_is_rejected():
    payload, context = inputs()
    payload["game"]["actions"][2]["subType"] = "Unrecorded Turnover"
    with pytest.raises(V3DecodeError, match="Unsupported Turnover subtype"):
        decode(payload, context)


def test_context_hash_mismatch_is_rejected():
    payload, context = inputs()
    with pytest.raises(V3DecodeError, match="raw PBP hash"):
        DecodedV3(json.dumps(payload).encode(), context)


def test_ambiguous_incoming_name_is_not_resolved_by_first_match():
    payload, context = inputs(
        wrap([e("sub", 600, HOME, 2, incoming=6), e("make", 590)])
    )
    context.roster[7]["names"].append("Player6")
    with pytest.raises(V3DecodeError, match="unresolved or ambiguous"):
        decode(payload, context)


def test_secondary_block_is_grouped_without_losing_source_rows():
    payload, context = inputs(
        wrap([e("miss"), e("rebound", 590, AWAY, 11), e("make", 580, AWAY, 11)])
    )
    secondary = dict(
        payload["game"]["actions"][1],
        actionType="",
        subType="",
        personId=11,
        teamId=AWAY,
        actionId=99,
        description="Player11 BLOCK (1 BLK)",
    )
    payload["game"]["actions"].insert(2, secondary)
    decoded = decode(payload, context)
    assert decoded.projected[1]["PLAYER3_ID"] == 11
    assert decoded.groups[2]["source_indices"] == (1, 2)
    assert sum(
        len(group["source_indices"]) for group in decoded.groups.values()
    ) == len(decoded.raw_rows)
    decoded.groups[2]["primary"]["description"] = "changed"
    assert (
        decoded.raw_rows[1]["description"]
        == payload["game"]["actions"][1]["description"]
    )


def test_duplicate_primary_group_is_rejected():
    payload, context = inputs()
    duplicate = dict(payload["game"]["actions"][1], actionId=99)
    payload["game"]["actions"].insert(2, duplicate)
    with pytest.raises(V3DecodeError, match="Ambiguous action group"):
        decode(payload, context)


def test_assist_after_points_annotation_resolves_exact_player():
    payload, context = inputs()
    payload["game"]["actions"][1][
        "description"
    ] = "Player1 Jump Shot (2 PTS) (Player2 1 AST)"
    assert decode(payload, context).projected[1]["PLAYER2_ID"] == 2


def test_explicit_three_point_value_preserves_raw_description():
    payload, context = inputs(wrap([e("make", value=3), e("turnover", 580, AWAY, 11)]))
    decoded = decode(payload, context)
    assert "3PT" not in decoded.raw_rows[1]["description"]
    loaded = StatsNbaV3PossessionLoader(decoded.source_bytes, context)
    assert loaded.events[1].shot_value == 3
    assert loaded.events[1].v3_source_row == payload["game"]["actions"][1]


def test_original_technical_before_start_repair_preserves_raw_order():
    events = [
        e("foul", 720, AWAY, 11, subtype="Technical"),
        e("ft", 720, HOME, 1, category="Technical", attempt=1, total=1, made=True),
        e("start", 720, 0, 0),
        e("make", 600),
        e("end", 0, 0, 0),
    ]
    payload, context = inputs(events)
    decoded = decode(payload, context)
    loaded = StatsNbaV3PossessionLoader(decoded.source_bytes, context)
    assert [event.event_num for event in loaded.events][:3] == [3, 1, 2]
    assert loaded.decoded.raw_rows == payload["game"]["actions"]
    assert loaded.events[0].v3_source_indices == (2,)
    assert loaded.diagnostics[0]["code"] == "legacy_order_repair"


def test_recorded_full_game_preserves_expected_boundaries_and_input_differences():
    prior = prepare_reference("prior")
    original = prepare_reference()
    loaded = load_paired(prior / "tests/data")
    old = worker(original, suite="paired", fixtures=original / "tests/data")["results"][
        0
    ]
    assert len(loaded.items) == 227
    assert [
        (p.period, p.events[-1].event_num, p.offense_team_id) for p in loaded.items
    ] == [(p["period"], p["end"], p["offense"]) for p in old["credits"]["groups"]]
    assert loaded.counts_by_team == {HOME: 114, AWAY: 112}
    assert loaded.events[-1].score == {HOME: 130, AWAY: 122}
    assert len(loaded.events) == 573
    assert sorted(
        i for event in loaded.events for i in event.v3_source_indices
    ) == list(range(596))
    seconds = defaultdict(Decimal)
    for stat in loaded.base_stats:
        if stat["stat_key"] in ("SecondsPlayedOff", "SecondsPlayedDef"):
            seconds[stat["player_id"]] += Decimal(str(stat["stat_value"]))
    for team in (HOME, AWAY):
        assert abs(
            sum(
                seconds[player]
                for player, facts in loaded.decoded.context.roster.items()
                if facts["team_id"] == team
            )
            - 15900
        ) < Decimal("0.000001")
    assert loaded.capabilities["source_order_checked"] is True
    assert loaded.capabilities["possession_sequence_checked"] is True
