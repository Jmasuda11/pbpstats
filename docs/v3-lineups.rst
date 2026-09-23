V3 substitution batches and lineups
===================================

``StatsNbaV3LineupLoader`` consumes classified events and explicit, offline
``V3LineupEvidence``. It requires declared complete roster and PBP coverage,
five eligible starters for each team in every represented period, and reviewed
batch membership covering every substitution exactly once. Missing or
conflicting evidence raises before lineups are returned. No network request,
implicit period-starter inference, or event-order repair runs.
Period lengths and overtime boundaries follow :doc:`v3-leagues`.

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

For name-only roles, roster candidates are narrowed to the validated lineup
immediately before the event. A single on-court match resolves the identity;
multiple on-court matches remain ambiguous, and no on-court match stays
unresolved. Jump-ball recipients are searched across both teams' five players;
team-scoped roles such as assists retain their team restriction. The filter
uses source order across substitutions, even when events share a clock, and
each period's separately evidenced starters. Incoming substitutions retain
their roster lookup and must enter from off court.

This refinement does not mutate the original classified roster facts or their
review fingerprints. The resulting ``lineups.items[].event`` and possession
events carry the narrowed candidates and the lineup evidence hash in the
participant provenance. Explicit IDs are validated, never reassigned by name.

With ``use_v2_rules=True``, an unknown opposing jumper is retained rather than
required for team possession accounting. The winning team must still be
established independently of the primary actor. Ambiguous on-court tip-recipient
candidates establish a team directly when every candidate belongs to the same
team; the individual identity and candidates remain ambiguous in the output.
Recorded actors and resolved participants still undergo on-court validation.

In that mode, a missing winning team can also be inferred by looking ahead to
the first supported control event in the same period, within 24 game-clock
seconds. A made/missed field goal identifies the shooting team; a supported
ball-control turnover at a later clock identifies the losing team; a shooting
foul identifies the opposing team, and an offensive foul identifies the fouling
team. Only substitutions and timeouts may intervene. Rebounds, free throws,
other fouls, violations, replays, ejections, another jump, period boundaries,
longer gaps and untimed periods do not support this inference. In particular,
a same-clock turnover may describe the loss that led to the jump, so it cannot
identify the subsequent recovery. Recorded recoveries take precedence.

This inference assumes the declared complete event stream has no omitted or
misordered change of control. It infers only the team: recipient status,
candidates and null player ID are preserved, and on-court name candidates must
be compatible with the inferred team. Participant evidence and an
``implied_jump_winner`` diagnostic cite the jump, intervening rows and control
event. Raw facts and review fingerprints remain unchanged; no external-source
hash is fabricated. All downstream lineup, possession and box-score checks
still apply. Strict mode does not enable look-ahead.

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
The :doc:`v3-possessions` layer separately validates foul/trip associations
and rebound/restart evidence before applying possession accounting.
