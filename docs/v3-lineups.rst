V3 substitution batches and lineups
===================================

``StatsNbaV3LineupLoader`` consumes classified events and explicit, offline
``V3LineupEvidence``. It requires declared complete roster and PBP coverage,
five eligible starters for each team in every represented period, and reviewed
batch membership covering every substitution exactly once. Missing or
conflicting evidence raises before lineups are returned. No network request,
implicit period-starter inference, or event-order repair runs.

Usage
-----

After loading the :doc:`v3-classification` layer with a complete context::

    from pbpstats.data_loader.stats_nba_v3.lineups import (
        StatsNbaV3LineupLoader,
        V3LineupEvidence,
    )

    evidence = V3LineupEvidence.from_file("reviewed-lineups.json")
    lineups = StatsNbaV3LineupLoader(classified, evidence)
    for item in lineups.items:
        print(item.event.kind, item.before, item.after)

Each immutable item retains its classified event, team-to-five-player mappings,
and substitution batch's primary source indices. Every event within one batch
has the same before/after mappings. Downstream duration accounting must use the
exact clock and avoid counting a same-clock batch more than once.

Evidence contract
-----------------

The JSON object contains ``schema_version=1``, ``game_id``, ``context_sha256``,
``snapshot_sha256``, ``periods``, and ``batches``. Duplicate JSON keys, nonfinite
numbers, invalid IDs, repeated periods, and missing provenance are rejected.
The original evidence bytes, SHA-256, and source location remain available.

``lineup_fingerprints(classified)`` supplies canonical semantic hashes of the
exact classified rows/identities and context, including roster provenance.
These are not raw-file checksums, nor proof that the lineup assertions are
correct. Changing a source location in context provenance changes its hash.
The loader validates assertions against the stream but cannot authenticate
external observations supplied by a caller.

Each ``periods`` record requires an integer ``period``, five distinct ``home``
IDs, five distinct ``away`` IDs, and nonempty ``source`` provenance. All must
belong to the declared team roster. An opening-game box-score position marker
can support Q1 after review; it does not support Q2, Q3, Q4, or overtime.
An ending lineup never silently becomes the next period's starters.

Each ``batches`` record requires nonempty ``source_indices`` and ``source``.
Indices refer to zero-based primary rows in the original snapshot. A batch
must contain contiguous substitutions in source order with identical period
and exact clock. Equal clocks alone do not create a batch. An intervening foul,
free throw, or other event prevents batching across that event. Separate
batches may share a clock when evidence establishes sequential transitions.

All outgoing players must already be on court and all incoming players must be
off court; duplicates and cross-team identities fail. Changes apply atomically
and leave exactly five players per team. Required actors and known secondary
participants must be on court. Technical-foul and technical-free-throw rows
are excluded from on-court identity checks and do not change the five.
Unresolved optional roles, including foul-drawn identities, stay unresolved.

The stream must start each contiguous period at its opening clock, end at zero,
and never increase the clock within a period. An unsupported correction or
out-of-order boundary fails explicitly rather than being silently repaired.

Recorded validation
-------------------

The 2019 Pelicans-Raptors fixture uses the separately reviewed
``nba_page_0021900001.json`` observation, a checksum-bound projection through
the production box-score loader, and ``lineups_0021900001.evidence.json``.
It replaces the test-only 2019 participant pool with 13 active players per
team, including all six DNPs. Inactive names are recorded separately and are
outside this declared game pool. The source is a DOM transcription, not a
native endpoint capture; no invented endpoint metadata is attached.

Q1 starter markers agree with the PBP. Each later period, including overtime,
has five separately required players per team: each has an on-court event or
outgoing substitution before any entrance in that period. The sidecar records
the exact witness row, role, and description for all 50 starter slots. This
deduction depends on the declared complete substitution stream, not on roster
completeness alone. Tests verify these witnesses, every transition in 31
reviewed batches (49 substitutions), and all 573 classified events.

Independent published player scoring reconciles to 130-122. Exact reconstructed
minutes total 265 per team; every player's time agrees with the displayed box
score within half a second and every DNP has zero time. NBA's displayed
``44:60`` and ``25:60`` strings are retained verbatim, with seconds carried only
in the comparison. The largest observed difference is 0.4 seconds.

The 2024 game still lacks independently reviewed roster/starter evidence.
These checks do not establish universal feed coverage or possession accuracy.
Connection to the possession engine is the next separate PR, with foul/trip
association, rebound/restart semantics, and possession accounting still required.
