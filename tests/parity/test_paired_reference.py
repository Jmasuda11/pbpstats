"""Input differences remain visible even when possession boundaries agree."""

from collections import Counter

from tools.parity.reference import prepare_reference
from tools.parity.run import worker


def test_paired_recording_identifies_fractional_clock_effect():
    original = prepare_reference()
    prior = prepare_reference("prior")
    old = worker(original, suite="paired", fixtures=original / "tests/data")["results"][
        0
    ]
    new = worker(prior, provider="prior_v3", suite="paired")["results"][0]
    assert old["status"] == new["status"] == "ok"
    assert len(old["credits"]["groups"]) == len(new["credits"]["groups"]) == 227
    assert [
        (p["period"], p["end"], p["offense"]) for p in old["credits"]["groups"]
    ] == [(p["period"], p["end"], p["offense"]) for p in new["credits"]["groups"]]
    assert (
        old["credits"]["score"]
        == new["credits"]["score"]
        == {"1610612761": 130, "1610612740": 122}
    )
    assert Counter(p["offense"] for p in old["credits"]["groups"] if p["counted"]) == {
        1610612761: 112,
        1610612740: 112,
    }
    assert Counter(p["offense"] for p in new["credits"]["groups"] if p["counted"]) == {
        1610612761: 114,
        1610612740: 112,
    }
    clock_effects = [
        (a["period"], a["start_seconds"], b["start_seconds"])
        for a, b in zip(old["snapshot"]["possessions"], new["snapshot"]["possessions"])
        if a["counted"] != b["counted"]
    ]
    assert clock_effects == [(1, 2, "2.8"), (3, 2, "2.1")]
    # Event numbers are a reviewed correspondence for THIS recording only.
    old_ids = [e["event_id"] for e in old["snapshot"]["events"]]
    new_ids = [e["event_id"] for e in new["snapshot"]["events"]]
    assert len(set(old_ids)) == len(old_ids) == 573
    assert len(set(new_ids)) == len(new_ids) == 573
    assert set(old_ids) == set(new_ids)
    assert [(a, b) for a, b in zip(old_ids, new_ids) if a != b] == [
        (171, 172),
        (172, 171),
    ]
