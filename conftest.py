"""Known upstream test failures, kept visible as strict expected failures.

At the pinned upstream revision (e7ccf2f), two free-throw tests fail because
their fixtures lack ``game_id``; they fail on the untouched original as well.
``tools.parity.baseline_tests`` verifies both failures and their cause against
the original. Here they only stop the upstream tox workflow from failing on
them: a different error, or either test passing, still fails the run.
"""

import pytest

KNOWN_UPSTREAM_FAILURES = {
    "tests/resources/test_free_throw.py::test_away_from_play_free_throw_type",
    "tests/resources/test_free_throw.py::test_flagrant_free_throw_type",
}


def pytest_collection_modifyitems(items):
    for item in items:
        if item.nodeid in KNOWN_UPSTREAM_FAILURES:
            item.add_marker(
                pytest.mark.xfail(
                    raises=AttributeError,
                    strict=True,
                    reason="Upstream fixture lacks game_id at e7ccf2f",
                )
            )
