Stats V3 input contract
=======================

This document specifies the boundary for adding Stats PlayByPlayV3 support.
It records observations from archived responses and requirements for the new
provider. Raw file ingestion is available; see :doc:`v3-file-loading`.
Source association and participant facts are described in :doc:`v3-participants`.
**V3 enhanced events and possession parsing are not implemented yet.**

The intended design is a separate ``stats_nba_v3`` provider whose enhanced
events implement the existing shared event interfaces. Reuse basketball rules
after checking their assumptions; do not replace raw V3 responses with V2
``resultSets`` tables. Historical V2 file parsing remains supported.

Recorded evidence
-----------------

``tests/data/v3/manifest.json`` identifies two complete archived responses and
one deliberately incomplete team-heave excerpt. It records hashes, provenance,
and available metadata. The published reference is pinned to an immutable
``swar/nba_api`` commit; the other inputs are user-provided archives whose
original capture process was not independently verified. These files do not
demonstrate current endpoint availability.

``tests/test_v3_data_contract.py`` characterizes the snapshots and establishes
the existing V2 comparison game's baseline. Those tests describe evidence;
they are not a V3 parser or a universal schema validator.

Identity, association, and order
--------------------------------

V3 actions appear under ``game.actions``. Preserve every raw action, original
array index, ``actionId``, ``actionNumber``, period, and clock. Raw data and
derived interpretation must remain separately accessible.

In the recorded games, a block or steal occupies an additional row with a blank
``actionType`` and shares its primary event's action number, period, and clock.
Do not deduplicate on action number. Associate related rows with validated
context; reject conflicting primary actions rather than keeping the first.
Do not assume identifiers are stable across later NBA corrections.

Preserve source order. For game ``0021900001``, the V3 order of a free-throw
sequence is ``170, 172, 171``, while corrected V2 uses ``170, 171, 172``.
Sorting by number would change the source's lane-violation placement. Any repair
must retain the original sequence and record its reason separately.

Participants and completeness
-----------------------------

Team rows put the team id in ``personId`` and set ``teamId`` to ``0``. In the
recorded games this covers 34 and 32 rows respectively, and two of the excerpt's
eight: team rebounds, timeouts, and delay-of-game and eight-second violations.
Resolve those to a team, never to a player; existing V2 handling makes the same
correction. Losing it corrupts rebound and possession-ownership accounting.

Use explicit participant IDs where present. Resolve description-only assists,
incoming substitutions, and jump-ball participants using team-scoped names,
roster information, and validated event context. Preserve the resolution evidence.
Ambiguous names must not select the first candidate.

Distinguish an absent relationship from a relationship whose participant is
unknown. Existing code can interpret a missing assister or stealer ID as an
unassisted basket or a different turnover type; that is not a safe default when
resolution failed.

V3 does not identify every player who drew a foul. For example, event ``29`` in
the paired game records an offensive foul by Kyle Lowry, but omits the Brandon
Ingram identity present in V2. This ordinary offensive foul has no free throw
at that clock to supply a candidate, and a roster cannot recover the relationship.
Other sequences do offer evidence: shooting foul ``18`` shares its period and
clock with free throws ``20`` and ``21``, whose shooter matches the V2 fouled
player. Attempt resolution before declaring an attribution unavailable, but
validate the foul/free-throw association and the shooter's role. A matching clock
alone is insufficient: `NBA free-throw rules`_ allow replacement shooters in
specified circumstances, including injury, and unrelated technical attempts can
occur at the same clock.

Reject unresolved facts that affect scoring, lineups, or possession ownership.
Missing optional attribution may leave those outputs usable, but dependent
player statistics must be explicitly unavailable or partial. A partial total
must not be presented as a complete one. The aggregate completeness interface
must be specified before exposing V3 statistics.

Clocks and statistical meaning
------------------------------

Preserve fractional precision and use consistent clock formatting. The paired
game has an event at ``PT00M02.80S`` where V2 records ``0:02``. This crosses the
existing two-second threshold for counting some end-of-period possessions.
Equal possession group counts therefore do not imply equal credited possessions
or playing-time statistics. Do not discard precision to force V2 parity.

Free throws in these snapshots have blank ``shotResult``, zero ``shotValue``,
and ``isFieldGoal=0``, including made attempts. Their outcomes require distinct
classification. Keep attempt position, live-ball eligibility after a miss, and
retained possession distinct; a final attempt does not always end possession.

The paired game's 205 ordinary field-goal coordinates match the cached shot
charts. This supports using those V3 coordinates for this sample, not treating
every zero coordinate as a real shot location or assuming all seasons agree.

Team heaves: a separate NBA accounting change
---------------------------------------------

Qualifying missed heaves count as team field-goal attempts without individual
player attempts (see the `NBA.com rule-change report`_). That is an NBA statistical
rule change, not a consequence of the V2-to-V3 format transition. Both
architectures must support this accounting.

The excerpt records ``Heave / Team Field Goal Attempt`` rows with zero person
and team IDs, while location, description, and surrounding data identify the
side. Recover the team from validated game context. Do not invent a shooter:
the absence of individual attribution is intentional. These rows also carry
``isFieldGoal=0``, ``shotValue=0`` and a blank ``shotResult``, so ``isFieldGoal``
does not select them; a filter on that flag silently drops every team heave.
Count the team FGA without crediting an individual player FGA, and test the
subsequent rebound and lineup aggregation separately. Apply the relevant season's
accounting rather than retroactively changing historical player-attributed attempts.

Offline behavior and validation
-------------------------------

File mode must use explicit cached game context, including roster and starter
recovery inputs, without hidden V2 or alternate-source requests. A full-game
roster alone does not establish every period's starting lineup. Report missing
context rather than silently guessing.

Validate game identity, payload structure, and required semantics. Preserve
unrecognized fields; unknown event semantics affecting possession must produce
contextual errors. Keep unavailable, malformed, incomplete, and completed games
distinct. An excerpt is never a complete-game parsing fixture.

Validate the new provider against reviewed event sequences, lineups, official
scores and compatible box-score totals, and source-row accounting. V2 comparisons
are useful references, not infallible expectations. Explain discrepancies caused
by timing precision, missing information, or legitimate source corrections.
Network smoke tests must remain separate from ordinary fixture-based CI.

.. _NBA.com rule-change report: https://www.nba.com/news/nbas-heave-rule-will-allow-deep-end-of-quarter-shots-without-hurting-shooting-percentages
.. _NBA free-throw rules: https://official.nba.com/rule-no-9-free-throws-and-penalties/
