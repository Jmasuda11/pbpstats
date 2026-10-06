"""Names are facts attached to explicit actors, never guessed participant IDs."""

from copy import deepcopy

import pytest

from tools.parity.participant_names import actor_alias, add_actor_aliases
from tools.parity.recorded import EvidenceError, require


def row(kind, subtype, description, player=1, team=100):
    return dict(
        actionNumber=27,
        actionType=kind,
        subType=subtype,
        description=description,
        personId=player,
        teamId=team,
    )


@pytest.mark.parametrize(
    "kind,subtype,description,name,role",
    [
        ("Substitution", "", "SUB: Thybulle FOR Hansen", "Hansen", "outgoing"),
        (
            "Rebound",
            "Unknown",
            "Jal. Williams REBOUND (Off:0 Def:1)",
            "Jal. Williams",
            "rebounder",
        ),
        (
            "Rebound",
            "Normal Rebound",
            "St. Curry REBOUND (Off:0 Def:2)",
            "St. Curry",
            "rebounder",
        ),
        ("", "", "Se. Curry STEAL (1 STL)", "Se. Curry", "secondary_actor"),
        ("", "", "Jay. Williams BLOCK (2 BLK)", "Jay. Williams", "secondary_actor"),
        (
            "Free Throw",
            "Free Throw 1 of 2",
            "Hansen Free Throw 1 of 2 (1 PTS)",
            "Hansen",
            "free_throw_shooter",
        ),
        (
            "Free Throw",
            "Free Throw 2 of 2",
            "MISS Hansen Free Throw 2 of 2",
            "Hansen",
            "free_throw_shooter",
        ),
        (
            "Free Throw",
            "Free Throw Technical",
            "Hansen Free Throw Technical (1 PTS)",
            "Hansen",
            "free_throw_shooter",
        ),
        (
            "Free Throw",
            "Free Throw Flagrant 1 of 2",
            "MISS Hansen Free Throw Flagrant 1 of 2",
            "Hansen",
            "free_throw_shooter",
        ),
    ],
)
def test_bounded_description_roles(kind, subtype, description, name, role):
    assert actor_alias(row(kind, subtype, description)) == (name, role)


@pytest.mark.parametrize(
    "event",
    [
        row("Made Shot", "Jump Shot", "Yang Jump Shot (Hansen 1 AST)"),
        row("Jump Ball", "", "Jump Ball Yang vs. Hansen: Tip to Curry"),
        row("Foul", "Technical", "TEAM T.Foul (Def. 3 Sec Hansen ) (Referee)"),
        row("Substitution", "Unknown", "SUB: Thybulle FOR Hansen"),
        row("Rebound", "Unknown", "Hansen REBOUND"),
        row("Rebound", "Unknown", "Hansen REBOUND (Off:0 Def:1) trailing text"),
        row("Rebound", "Unreviewed", "Hansen REBOUND (Off:0 Def:1)"),
        row("Free Throw", "Free Throw 1 of 2", "Hansen Free Throw 2 of 2 (1 PTS)"),
        row("Free Throw", "Free Throw Unreviewed", "Hansen Free Throw Unreviewed"),
        row("", "", "Hansen STEAL (1 STL) trailing text"),
        row("", "Unknown", "Hansen STEAL (1 STL)"),
    ],
)
def test_no_alias_from_other_roles_or_unreviewed_grammar(event):
    assert actor_alias(event) is None


def test_witness_keeps_exact_identity_and_source_without_changing_rows():
    rows = [row("Substitution", "", "SUB: Thybulle FOR Hansen")]
    original = deepcopy(rows)
    roster = {1: dict(team_id=100, names=["Yang", "H. Yang"])}
    witnesses = add_actor_aliases(rows, roster, require)
    assert rows == original
    assert roster[1]["names"] == ["Yang", "H. Yang", "Hansen"]
    assert witnesses == [
        dict(
            source_index=0,
            action_number=27,
            player_id=1,
            team_id=100,
            name="Hansen",
            role="outgoing",
        )
    ]
    assert "Thybulle" not in roster[1]["names"]


def test_alias_cannot_overwrite_a_different_id_bound_name():
    roster = {
        1: dict(team_id=100, names=["Yang"]),
        2: dict(team_id=100, names=["Hansen"]),
    }
    with pytest.raises(EvidenceError) as error:
        add_actor_aliases(
            [row("Rebound", "Unknown", "Hansen REBOUND (Off:0 Def:1)")], roster, require
        )
    assert error.value.code == "participant_alias_conflict"
    assert error.value.details["candidates"] == [2]


def test_preexisting_collisions_are_not_removed_or_disambiguated():
    roster = {
        1: dict(team_id=100, names=["Williams"]),
        2: dict(team_id=100, names=["Williams"]),
    }
    original = deepcopy(roster)
    assert (
        add_actor_aliases(
            [row("Rebound", "Unknown", "Williams REBOUND (Off:0 Def:1)")],
            roster,
            require,
        )
        == []
    )
    assert roster == original


@pytest.mark.parametrize("identity", [0, 100, 99])
def test_non_roster_actors_cannot_add_aliases(identity):
    roster = {1: dict(team_id=100, names=["Yang"])}
    assert (
        add_actor_aliases(
            [row("Substitution", "", "SUB: Hansen FOR Yang", player=identity)],
            roster,
            require,
        )
        == []
    )
    assert roster[1]["names"] == ["Yang"]
