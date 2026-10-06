"""Do not disguise missing games or changed evidence as parser progress."""

from copy import deepcopy

import pytest

from tools.parity.corpus_diff import compare_audits


def report():
    return {
        "inventory_sha256": "frozen",
        "previous_report": {"sha256": "prior"},
        "implementation_hashes": {"decoder.py": "before"},
        "games": [
            {
                "game_id": str(i),
                "capture": str(i),
                "previous_status": "validated",
                "status": "blocked",
                "context_prepared": True,
                "adapter_completed": False,
                "full_game_validated": False,
                "source_hashes": {"pbp.json": "source"},
                "first_blocker": {
                    "stage": "adapter",
                    "code": "unknown_shot",
                    "source_indices": [1],
                    "message": "shot unknown",
                    "raw_context": [],
                },
            }
            for i in range(3)
        ],
    }


def test_every_game_retained_when_blocker_moves_and_one_game_passes():
    before = report()
    after = deepcopy(before)
    after["games"][0]["first_blocker"]["code"] = "unknown_actor"
    after["games"][1].update(status="checks_passed", adapter_completed=True)
    del after["games"][1]["first_blocker"]
    after["implementation_hashes"]["decoder.py"] = "after"
    difference = compare_audits(before, after)
    assert difference["summary"]["games"] == 3
    assert difference["summary"]["changed"] == 2
    assert difference["summary"]["unchanged"] == 1
    assert difference["summary"]["status_transitions"] == {
        "blocked -> blocked": 2,
        "blocked -> checks_passed": 1,
    }
    assert difference["implementation_changes"] == ["decoder.py"]
    assert [g["game_id"] for g in difference["games"]] == ["0", "1", "2"]


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "inventory", "prior", "source", "capture", "status"],
)
def test_changed_scope_or_evidence_is_not_comparable(mutation):
    before = report()
    after = deepcopy(before)
    if mutation == "missing":
        after["games"].pop()
    elif mutation == "duplicate":
        after["games"].append(deepcopy(after["games"][0]))
    elif mutation == "inventory":
        after["inventory_sha256"] = "different"
    elif mutation == "prior":
        after["previous_report"]["sha256"] = "different"
    elif mutation == "source":
        after["games"][0]["source_hashes"]["pbp.json"] = "different"
    elif mutation == "capture":
        after["games"][0]["capture"] = "different"
    else:
        after["games"][0]["previous_status"] = "blocked"
    with pytest.raises(ValueError):
        compare_audits(before, after)


def test_same_error_at_later_source_row_is_a_changed_outcome():
    before = report()
    after = deepcopy(before)
    after["games"][0]["first_blocker"]["source_indices"] = [8]
    assert compare_audits(before, after)["summary"]["changed"] == 1
