V3 event classification
========================

``StatsNbaV3EventLoader`` consumes ``StatsNbaV3ParticipantLoader`` and produces
immutable ``V3ClassifiedEvent`` facts. It preserves the participant results,
every associated source row, exact clocks, source ordering, and source subtype.
It does not construct enhanced-event statistics, lineups, or possessions.

.. code-block:: python

    from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader

    events = StatsNbaV3EventLoader(participant_loader)
    for event in events.items:
        print(event.kind, event.recorded_points, event.group.source_indices)

Supported families are field goals, free throws, rebounds, fouls, turnovers,
violations, substitutions, jump balls, timeouts, period starts/ends, replays,
and recorded team-only heaves. The exact supported non-shot subtypes are listed
in ``classification.SUBTYPES`` and tested against the committed fixtures.
Unknown possession-affecting semantics raise with game and source-row context;
they are never silently ignored or assigned an ordinary foul/turnover meaning.
Unfamiliar shot styles can retain sufficient explicit scoring fields without
claiming a known shot style or zone.

Field goals require consistent ``actionType``, ``shotResult``, ``shotValue``,
``isFieldGoal``, team, and shooter evidence. Value comes from ``shotValue``;
a missing ``3PT`` description token does not turn a three into a two. A recorded
three-point token conflicting with a two-point value is rejected. Non-field-goal
rows must retain the inspected zero/blank scoring-field convention; an unfamiliar
convention fails rather than silently contributing zero points.

Recorded free throws have blank shot results and zero raw shot values. Their
outcomes require a recognized description matching the subtype, including the
explicit miss prefix or made-attempt points annotation. ``free_throw`` records category, attempt, total, and restart
knowledge separately. ``is_last_attempt`` means trip position, not possession end:

* Regular attempts retain ``restart="context_required"``. Foul/trip linkage,
  violations, replacement shooters, and retained-possession penalties need
  separate validation, including when the subtype says ``1 of 1`` or ``2 of 2``.
* Explicit clear-path and flagrant attempts retain
  ``restart="shooting_team_retains"``.
* Technical attempts retain ``restart="resume_interrupted_play"``; this does not
  award possession to the shooter simply because that team took the free throw.

These distinctions follow `NBA Rule 12
<https://official.nba.com/rule-no-12-fouls-and-penalties/>`_ and the live/dead
free-throw distinction in `Rule 9
<https://official.nba.com/rule-no-9-free-throws-and-penalties/>`_. Explicit
clear-path/flagrant vocabulary has synthetic tests, not recorded coverage in
the current committed full-game fixtures. Other special penalties remain
unsupported until fixture evidence and contextual tests are added.

``recorded_points`` describes the recorded attempt; it is not a guarantee that
a later correction cannot cancel it. Replay and violation rows remain visible
for later reconciliation. Team heaves retain team attribution without inventing
a shooter or a two/three-point value from zero-valued source fields. Actual
team-attempt accounting belongs to the subsequent statistics integration.

Rebound ``Normal Rebound``/``Unknown`` labels do not distinguish live from
dead-ball rebounds or offensive from defensive rebounds; ``rebound_type`` stays
``None`` until shot/sequence evidence is validated. Likewise, a bad pass with
an unresolved stealer does not become an out-of-bounds turnover.

Validation classifies all 573/445 associated events in the two complete PBP
fixtures, preserves every raw row, and reconciles recorded points with every
available cumulative score. The paired V2 fixture provides a bounded comparison
of event families; no V2 projection or general semantic-parity claim is made.
The tests require no test-only roster to classify explicit scoring evidence;
description-only participant roles remain unresolved.

The next layer must supply separately validated roster and period-starter
evidence, apply substitution batches, and validate lineup transitions before
the possession engine depends on these events. Fresh matching roster requests
remain unavailable; this classification layer does not certify roster coverage.
