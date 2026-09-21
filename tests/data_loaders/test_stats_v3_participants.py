import json
import socket
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pbpstats.data_loader.stats_nba_v3.association import associate_actions
from pbpstats.data_loader.stats_nba_v3.context import V3GameContext, V3RosterPlayer
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData

DATA = Path(__file__).resolve().parents[1] / "data"
GAME_ID = "0021900001"
HOME, AWAY = 1610612761, 1610612740


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Participant resolution attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def context():
    return V3GameContext(
        GAME_ID,
        HOME,
        AWAY,
        (
            V3RosterPlayer(1, HOME, ("Smith", "A. Smith")),
            V3RosterPlayer(2, HOME, ("Brown", "B. Brown")),
            V3RosterPlayer(3, AWAY, ("Smith", "C. Smith")),
            V3RosterPlayer(4, AWAY, ("Green", "D. Green")),
        ),
        True,
        "Synthetic roster for adversarial cases",
    )


def row(number=1, kind="Made Shot", person=1, team=HOME, description=None, **fields):
    result = {
        "actionId": number,
        "actionNumber": number,
        "period": 1,
        "clock": "PT11M00.00S",
        "actionType": kind,
        "subType": "",
        "personId": person,
        "teamId": team,
        "location": "h" if team == HOME else "v",
        "description": "Smith 2' Layup (2 PTS)" if description is None else description,
    }
    result.update(fields)
    return result


def raw_loader(rows, game_id=GAME_ID):
    source = SimpleNamespace(
        load_data=lambda gid: V3PbpSourceData(
            payload={"game": {"gameId": game_id, "actions": rows}}
        )
    )
    return StatsNbaV3PbpLoader(game_id, source)


def interpret(rows, context, snapshot_complete=True):
    return StatsNbaV3ParticipantLoader(
        raw_loader(rows, context.game_id), context, snapshot_complete=snapshot_complete
    )


def recorded_context(raw, home, away):
    # Test-only alias pool. PBP actors are NOT a production complete-roster source.
    # For 2019, resolved identities are independently compared with every V2 role.
    names, teams = defaultdict(set), {}
    for action in raw.data:
        pid, tid = action["personId"], action["teamId"]
        if (
            pid
            and pid not in (home, away)
            and tid
            and action["actionType"] not in ("period", "Instant Replay")
        ):
            names[pid].update(
                name for name in (action["playerName"], action["playerNameI"]) if name
            )
            teams[pid] = tid
    return V3GameContext(
        raw.game_id,
        home,
        away,
        tuple(
            V3RosterPlayer(pid, teams[pid], tuple(sorted(aliases)))
            for pid, aliases in names.items()
        ),
        True,
        "Test-only recorded participant pool; not an official roster",
    )


@pytest.mark.parametrize(
    "game_id, home, away, expected",
    [
        (GAME_ID, HOME, AWAY, (573, 11, 12, 53, 49)),
        ("0022400001", 1610612738, 1610612737, (445, 23, 7, 63, 43)),
    ],
)
def test_recorded_games_account_for_every_row_and_resolve_secondary_roles(
    game_id, home, away, expected
):
    raw = StatsNbaV3PbpLoader(game_id, StatsNbaV3PbpFileLoader(DATA))
    before = raw.source_data
    result = StatsNbaV3ParticipantLoader(
        raw, recorded_context(raw, home, away), snapshot_complete=True
    )
    assert len(result.items) == expected[0]
    indices = [index for event in result.items for index in event.group.source_indices]
    assert sorted(indices) == list(range(len(raw.items)))
    assert [e.group.primary.order for e in result.items] == sorted(
        e.group.primary.order for e in result.items
    )
    counts = Counter(
        (role, p.status) for e in result.items for role, p in e.participants.items()
    )
    assert (
        tuple(
            counts[pair]
            for pair in (
                ("stealer", "explicit"),
                ("blocker", "explicit"),
                ("assister", "resolved"),
                ("incoming", "resolved"),
            )
        )
        == expected[1:]
    )
    assert (
        counts["opposing_jumper", "resolved"]
        == counts["tip_recipient", "resolved"]
        == 2
    )
    assert raw.source_data == before


def test_every_recoverable_secondary_identity_matches_paired_v2():
    raw = StatsNbaV3PbpLoader(GAME_ID, StatsNbaV3PbpFileLoader(DATA))
    result = StatsNbaV3ParticipantLoader(
        raw, recorded_context(raw, HOME, AWAY), snapshot_complete=True
    )
    table = json.loads((DATA / f"pbp/stats_{GAME_ID}.json").read_bytes())["resultSets"][
        0
    ]
    rows = [dict(zip(table["headers"], values)) for values in table["rowSet"]]
    old = {item["EVENTNUM"]: item for item in rows}
    fields = {
        "assister": "PLAYER2_ID",
        "incoming": "PLAYER2_ID",
        "stealer": "PLAYER2_ID",
        "blocker": "PLAYER3_ID",
        "opposing_jumper": "PLAYER2_ID",
        "tip_recipient": "PLAYER3_ID",
    }
    comparisons = Counter()
    for event in result.items:
        for role, field in fields.items():
            if role in event.participants:
                participant = event.participants[role]
                assert participant.player_id == (
                    old[event.group.primary.action_number][field] or None
                )
                if participant.player_id is not None:
                    comparisons[role] += 1
    assert comparisons == {
        "assister": 53,
        "incoming": 49,
        "stealer": 11,
        "blocker": 12,
        "opposing_jumper": 2,
        "tip_recipient": 2,
    }


def test_replay_person_ids_are_not_mistaken_for_players():
    raw = StatsNbaV3PbpLoader(GAME_ID, StatsNbaV3PbpFileLoader(DATA))
    result = StatsNbaV3ParticipantLoader(raw, recorded_context(raw, HOME, AWAY))
    replay = next(e for e in result.items if e.group.primary.action_number == 137)
    assert replay.group.primary.data["personId"] == 133
    assert replay.team_id is None
    assert replay.participants["actor"].status == "not_applicable"
    assert replay.participants["actor"].player_id is None


def test_team_heaves_keep_intentional_team_only_attribution():
    payload = json.loads(
        (DATA / "pbp/stats_v3_0042500317_heaves_excerpt.json").read_bytes()
    )
    ctx = V3GameContext("0042500317", 1610612760, 1610612759)
    events = interpret(payload["game"]["actions"], ctx, snapshot_complete=False).items
    heaves = [e for e in events if e.group.primary.action_type == "Heave"]
    assert len(heaves) == 2
    for event in heaves:
        assert event.team_id == 1610612760
        assert event.participants["actor"].status == "not_applicable"
        assert event.participants["actor"].player_id is None


@pytest.mark.parametrize(
    "kind, description, secondary_kind",
    [
        ("Turnover", "Green STEAL (1 STL)", "steal"),
        ("Missed Shot", "Green BLOCK (1 BLK)", "block"),
    ],
)
def test_association_uses_primary_order_and_preserves_secondary_before_primary(
    kind, description, secondary_kind
):
    secondary = row(2, "", 4, AWAY, description, actionNumber=1)
    primary = row(1, kind)
    groups = associate_actions(raw_loader([secondary, primary]).items)
    assert len(groups) == 1
    assert groups[0].primary.order == 1
    assert groups[0].source_indices == (0, 1)
    assert getattr(groups[0], secondary_kind).order == 0


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"clock": "PT10M59S"}, "conflicting periods or clocks"),
        ({"period": 2}, "conflicting periods or clocks"),
        ({"description": "Green UNKNOWN (1 X)"}, "unrecognized blank-type"),
        ({"description": "Green BLOCK (1 BLK)"}, "requires a Missed Shot"),
        ({"actionType": "Turnover"}, "exactly one typed primary"),
        ({"actionId": 1}, "repeated actionId"),
    ],
)
def test_conflicting_associations_raise_with_source_rows(change, reason):
    secondary = row(2, "", 4, AWAY, "Green STEAL (1 STL)", actionNumber=1)
    secondary.update(change)
    with pytest.raises(ValueError, match=reason) as error:
        associate_actions(raw_loader([row(kind="Turnover"), secondary]).items)
    assert GAME_ID in str(error.value)
    assert "source rows" in str(error.value)


def test_association_rejects_exact_clocks_that_round_to_the_same_float():
    primary = row(kind="Turnover", clock="PT00M02.80000000000000001S")
    secondary = row(
        2,
        "",
        4,
        AWAY,
        "Green STEAL (1 STL)",
        actionNumber=1,
        clock="PT00M02.80000000000000002S",
    )
    items = raw_loader([primary, secondary]).items
    assert items[0].seconds_remaining == items[1].seconds_remaining
    assert items[0].seconds_remaining_exact != items[1].seconds_remaining_exact
    with pytest.raises(ValueError, match="conflicting periods or clocks"):
        associate_actions(items)


def test_orphan_secondary_and_duplicate_secondary_are_rejected():
    secondary = row(2, "", 4, AWAY, "Green STEAL (1 STL)", actionNumber=1)
    with pytest.raises(ValueError, match="exactly one typed primary"):
        associate_actions(raw_loader([secondary]).items)
    with pytest.raises(ValueError, match="multiple steal rows"):
        associate_actions(
            raw_loader(
                [row(kind="Turnover"), secondary, dict(secondary, actionId=3)]
            ).items
        )


def test_mixed_games_and_reordered_items_are_rejected():
    first = raw_loader([row()]).items[0]
    other = raw_loader([row(2)], "0022400001").items[0]
    with pytest.raises(ValueError, match="different games"):
        associate_actions([first, other])
    with pytest.raises(ValueError, match="increasing source positions"):
        associate_actions(reversed(raw_loader([row(), row(2)]).items))


def test_unknown_typed_events_and_fractional_clocks_remain_unmodified():
    actions = [
        row(9, "Future Event", clock="PT00M02.80S"),
        row(3, "Turnover", clock="PT00M02.80S"),
        row(4, "", 4, AWAY, "Green STEAL (1 STL)", actionNumber=3, clock="PT0M2.8S"),
    ]
    raw = raw_loader(actions)
    groups = associate_actions(raw.items)
    assert [g.primary.action_number for g in groups] == [9, 3]
    assert groups[1].source_indices == (1, 2)
    assert raw.data == actions


def test_names_are_team_scoped_and_absent_is_not_unresolved(context):
    assisted = row(person=2, description="Brown Layup (2 PTS) (Smith 1 AST)")
    event = interpret([assisted], context).items[0]
    assert event.require_player("assister") == 1
    assert event.participants["assister"].candidates == (1,)
    absent = interpret([row()], context).items[0].participants["assister"]
    unknown = (
        interpret([row(description="")], context).items[0].participants["assister"]
    )
    assert absent.status == "absent"
    assert unknown.status == "unresolved"
    assert absent.player_id is unknown.player_id is None


def test_homonyms_are_ambiguous_and_never_choose_first(context):
    context = replace(
        context,
        players=context.players + (V3RosterPlayer(5, HOME, ("Smith", "E. Smith")),),
    )
    event = interpret(
        [row(person=2, description="Brown Layup (2 PTS) (Smith 1 AST)")], context
    ).items[0]
    assert event.participants["assister"].status == "ambiguous"
    assert event.participants["assister"].candidates == (1, 5)
    with pytest.raises(ValueError, match="assister is ambiguous"):
        event.require_player("assister")
    resolved = interpret(
        [row(person=2, description="Brown Layup (2 PTS) (E. Smith 1 AST)")], context
    ).items[0]
    assert resolved.require_player("assister") == 5


def test_incomplete_roster_never_certifies_a_unique_name(context):
    context = replace(context, roster_complete=False)
    event = interpret(
        [row(person=2, description="Brown Layup (2 PTS) (Smith 1 AST)")], context
    ).items[0]
    assert event.require_player("actor") == 2
    assert event.participants["assister"].status == "unresolved"
    assert event.participants["assister"].candidates == (1,)
    with pytest.raises(ValueError, match="assister is unresolved"):
        event.require_player("assister")


def test_explicit_ids_disambiguate_names_but_conflicts_fail(context):
    context = replace(
        context, players=context.players + (V3RosterPlayer(5, HOME, ("Smith",)),)
    )
    action = row(
        person=2, description="Brown Layup (2 PTS) (Smith 1 AST)", assistPersonId=5
    )
    assert interpret([action], context).items[0].require_player("assister") == 5
    action["description"] = "Brown Layup (2 PTS) (A. Smith 1 AST)"
    with pytest.raises(ValueError, match="contradicts description"):
        interpret([action], context)


@pytest.mark.parametrize(
    "action, role, expected",
    [
        (
            row(
                person=2,
                description="Brown Layup (2 PTS) (Smith 1 AST)",
                assistPersonId=5,
            ),
            "assister",
            5,
        ),
        (
            row(kind="Substitution", person=5, description="SUB: Brown FOR Smith"),
            "outgoing",
            5,
        ),
        (
            row(
                kind="Jump Ball",
                person=5,
                description="Jump Ball Smith vs. Green: Tip to Brown",
            ),
            "actor",
            5,
        ),
    ],
)
def test_partial_alias_pool_cannot_disprove_explicit_identity(
    context, action, role, expected
):
    context = replace(context, roster_complete=False)
    assert interpret([action], context).items[0].require_player(role) == expected


@pytest.mark.parametrize(
    "kind, description, known_role, expected",
    [
        ("Substitution", "SUB: Brown FOR Smith", "incoming", 2),
        ("Jump Ball", "Jump Ball Smith vs. Green: Tip to Brown", "opposing_jumper", 4),
    ],
)
def test_missing_actor_does_not_create_a_description_conflict(
    context, kind, description, known_role, expected
):
    event = interpret(
        [row(kind=kind, person=0, description=description)], context
    ).items[0]
    assert event.participants["actor"].status == "unresolved"
    assert event.require_player(known_role) == expected


def test_fouler_cannot_draw_own_foul_even_without_roster(context):
    context = replace(context, players=(), roster_complete=False)
    action = row(kind="Foul", team=0, location="", foulDrawnPersonId=1)
    with pytest.raises(ValueError, match="foul_drawn cannot be the primary actor"):
        interpret([action], context)


@pytest.mark.parametrize(
    "fields, reason",
    [
        ({"personId": True}, "personId must"),
        ({"teamId": -1}, "teamId must"),
        ({"personId": 999}, "outside the complete roster"),
        ({"teamId": 999}, "teamId is outside"),
        ({"location": "v"}, "disagree"),
        ({"location": "unknown"}, "unrecognized team location"),
        ({"personId": 3}, "disagree"),
        ({"assistPersonId": 3}, "conflicts with the participant's team"),
        ({"assistPersonId": 1}, "assister cannot be the primary actor"),
    ],
)
def test_contradictory_identities_are_rejected(context, fields, reason):
    with pytest.raises(ValueError, match=reason):
        interpret([row(**fields)], context)


@pytest.mark.parametrize(
    "secondary, reason",
    [
        (row(2, "", 2, HOME, "Brown STEAL (1 STL)", actionNumber=1), "opposing team"),
        (
            row(2, "", 0, AWAY, "Green STEAL (1 STL)", actionNumber=1),
            "explicit player ID",
        ),
        (
            row(2, "", AWAY, AWAY, "Team STEAL (1 STL)", actionNumber=1),
            "identifies a team",
        ),
    ],
)
def test_split_participant_must_be_an_opposing_player(context, secondary, reason):
    with pytest.raises(ValueError, match=reason):
        interpret([row(kind="Turnover"), secondary], context)


def test_missing_secondary_is_unknown_until_snapshot_is_declared_complete(context):
    raw = raw_loader([row(kind="Turnover")])
    assert (
        StatsNbaV3ParticipantLoader(raw, context)
        .items[0]
        .participants["stealer"]
        .status
        == "unresolved"
    )
    assert (
        StatsNbaV3ParticipantLoader(raw, context, snapshot_complete=True)
        .items[0]
        .participants["stealer"]
        .status
        == "absent"
    )


def test_substitutions_keep_outgoing_and_incoming_distinct(context):
    action = row(kind="Substitution", description="SUB: Brown FOR Smith")
    event = interpret([action], context).items[0]
    assert event.require_player("outgoing") == 1
    assert event.require_player("incoming") == 2
    action["description"] = "SUB: Nobody FOR Smith"
    unknown = interpret([action], context).items[0]
    with pytest.raises(ValueError, match="incoming is unresolved"):
        unknown.require_player("incoming")
    action.update(description="unrecognized text", incomingPersonId=2)
    assert interpret([action], context).items[0].require_player("incoming") == 2


@pytest.mark.parametrize(
    "description, reason",
    [
        ("SUB: Smith FOR Smith", "incoming cannot"),
        ("SUB: Smith FOR Brown", "outgoing substitution name contradicts"),
    ],
)
def test_substitution_conflicts_are_rejected(context, description, reason):
    with pytest.raises(ValueError, match=reason):
        interpret([row(kind="Substitution", description=description)], context)


def test_jump_ball_recipient_can_be_ambiguous_across_teams(context):
    action = row(
        kind="Jump Ball", description="Jump Ball Smith vs. Green: Tip to Smith"
    )
    event = interpret([action], context).items[0]
    assert event.require_player("opposing_jumper") == 4
    assert event.participants["tip_recipient"].status == "ambiguous"
    assert event.participants["tip_recipient"].candidates == (1, 3)
    action["description"] = "Jump Ball Smith vs. Green: Tip to C. Smith"
    assert interpret([action], context).items[0].require_player("tip_recipient") == 3


def test_foul_drawn_is_not_guessed_from_same_clock_free_throw(context):
    foul = row(kind="Foul", subType="Shooting")
    free_throw = row(2, "Free Throw", 3, AWAY, "Smith Free Throw 1 of 2")
    event = interpret([foul, free_throw], context).items[0]
    assert event.participants["foul_drawn"].status == "unresolved"
    with pytest.raises(ValueError, match="foul_drawn is unresolved"):
        event.require_player("foul_drawn")
    foul["foulDrawnPersonId"] = 3
    assert (
        interpret([foul, free_throw], context).items[0].require_player("foul_drawn")
        == 3
    )


def test_context_and_result_are_defensive_and_keep_provenance(context):
    aliases = ["Other"]
    player = V3RosterPlayer(5, HOME, aliases)
    aliases.append("Smith")
    assert player.aliases == ("Other",)
    rows = [row(description="Smith Layup (2 PTS) (Brown 1 AST)")]
    before = deepcopy(rows)
    loader = interpret(rows, context)
    assert loader.context.roster_source == context.roster_source
    event = loader.items[0]
    assert event.participants["assister"].source_indices == (0,)
    assert event.participants["assister"].name == "Brown"
    with pytest.raises(TypeError):
        event.participants["assister"] = event.participants["actor"]
    event.group.primary.data["personId"] = 999
    assert rows == before
    assert event.require_player("actor") == 1


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"home_team_id": AWAY}, "distinct positive team"),
        ({"home_team_id": True}, "distinct positive team"),
        ({"roster_complete": "yes"}, "must be a boolean"),
        ({"roster_source": ""}, "requires its source"),
        ({"players": ()}, "cover both teams"),
    ],
)
def test_invalid_context(context, change, reason):
    with pytest.raises(ValueError, match=reason):
        replace(context, **change)


def test_duplicate_or_foreign_roster_players_are_rejected(context):
    with pytest.raises(ValueError, match="duplicate roster player"):
        replace(context, players=context.players + (context.players[0],))
    with pytest.raises(ValueError, match="conflicts with game context"):
        replace(
            context, players=context.players + (V3RosterPlayer(99, 999, ("Unknown",)),)
        )


def test_context_game_id_and_snapshot_flag_are_validated(context):
    with pytest.raises(ValueError, match="different game IDs"):
        StatsNbaV3ParticipantLoader(
            raw_loader([row()]), replace(context, game_id="0022400001")
        )
    with pytest.raises(ValueError, match="snapshot_complete must be a boolean"):
        StatsNbaV3ParticipantLoader(
            raw_loader([row()]), context, snapshot_complete="yes"
        )


def test_aliases_preserve_suffixes_accents_and_initials(context):
    players = context.players + (
        V3RosterPlayer(5, HOME, ("Butler III", "J. Butler III")),
        V3RosterPlayer(6, AWAY, ("Jokić",)),
    )
    context = replace(context, players=players)
    assert context.candidates("  j. BUTLER III  ", HOME) == (5,)
    assert context.candidates("Butler", HOME) == ()
    assert context.candidates("Jokic", AWAY) == ()
    assert context.candidates("Jokić", AWAY) == (6,)
