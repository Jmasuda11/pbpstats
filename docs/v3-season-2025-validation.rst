NBA 2025-26 ingestion validation
================================

Final Stats V3 snapshots contain stale running-score annotations, replay markers,
sequential substitutions, replacement FT shooters and jump balls with missing
recovery information. The opt-in ``use_v2_rules=True`` path adapts bounded V2
behavior for these sequences; strict processing remains the default. See
:doc:`v3-game-loading`, :doc:`v3-lineups` and :doc:`v3-possessions` for the contracts.

Scope and provenance
--------------------

The parser also recognizes recorded 2025 event vocabulary, roster-name variants,
double fouls, coach ejections and blocked team heaves. Name-only participants are
narrowed against on-court players. Explicit IDs and original source rows remain
intact, and unknown individuals retain null player IDs. Inferred jump recovery
teams have a separate ``implied_jump_winner`` diagnostic with supporting rows.

Look-ahead uses the next supported control event within the same period and
24 game-clock seconds, skipping only substitutions and timeouts. It assumes
there is no omitted or misordered change of control. Same-clock turnovers,
loose-ball fouls, jump violations, technical FTs and other ambiguous sequences
still block this inference. A known recovering team does not identify the
individual tip recipient. This is not a general event-correction engine.

Validation on September 23, 2026
--------------------------------

The complete repository test suite passed on Python 3.12: **897 tests**, including
**750 native V3 tests**. Run ``python -m pytest -q`` with the dependencies declared
in ``tox.ini``. The existing CI matrix covers Python 3.8 through 3.12; the local
result does not claim that every matrix version has run.

The separate Cheeseburger ingestion application passed **59 Django tests** on
an isolated temporary PostgreSQL database. Its offline validator checked all
**1,230** cached NBA 2025-26 regular-season games with adapter 2.3, applying
parser validation plus player-statistics, minutes and box-score reconciliation:

.. list-table:: Offline season outcomes
   :header-rows: 1

   * - Revision of the V2 adaptation
     - Validated
     - Blocked
   * - Initial adaptation
     - 854
     - 376
   * - Recorded shooters, partial jump identities and lane handling
     - 946
     - 284
   * - Bounded jump recovery look-ahead
     - 999
     - 231

All previous 946 successes still validate with unchanged possession counts.
The 53 newly validated games contain 58 inferred jump recoveries. Of the 105
previous unknown-winner games, 53 validate, 41 still lack a supported winner and
11 reach another blocker. These are each game's first failure, not counts of
every issue within a game.

The largest remaining groups are 41 unknown jump winners, 36 consecutive
possession/restart conflicts, 24 unmatched FT awards, 21 off-court identity
cases, 13 conflicting offensive events, 13 unsupported one-shot awards,
11 missing FT trips and 10 ambiguous incoming substitutes. Another 62 games
have smaller source, lineup, FT/rebound, ejection or event-order issues.

Original capture hashes were unchanged, and the audit's parser source hashes
matched the implementation. Validation used temporary copies with networking
and database connections disabled; no season backfill was performed. The
cached season recordings and ingestion validator belong to the separate
application and are not included in this repository. Repository tests retain
synthetic counterexamples and the existing recorded league fixtures.

For traceability, the local full report ``jump-lookahead-validation.json`` has
SHA-256 ``92c98f03ac618e5313a02c48ada8d151a0b718af5ee2ab458829e9c1cfef1c10``;
its 946/284 predecessor ``v2-actor-lane-validation.json`` has SHA-256
``de5b34369d4ad726cbbee05e02ff35988fa4cc05db9714c089b3e18fff9d025e``.

These results establish the checked parser and adapter behavior, not complete
league coverage, independent verification of every inferred possession, or
availability of live NBA endpoints. Remaining failures stay explicit.
