V3 possession integration
=========================

``StatsNbaV3PossessionLoader`` connects the validated :doc:`v3-lineups` output
to the shared possession engine. It returns standard ``Possession`` objects
without projecting V3 rows into V2 dictionaries. Native events retain their
classified facts, source indices, resolved participants, and validated lineups.
Loading is offline and does not read overrides or repair event order.

Usage and outputs
-----------------

After constructing the lineup loader with separately reviewed starters for
every period and explicit substitution batches::

    from pbpstats.data_loader.stats_nba_v3.possessions import (
        StatsNbaV3PossessionLoader,
    )

    loaded = StatsNbaV3PossessionLoader(lineups)
    for possession in loaded.items:
        print(possession.period, possession.number, possession.offense_team_id,
              possession.start_time, possession.end_time,
              possession.start_score_margin, possession.possession_start_type)

    print(loaded.counts_by_team)
    stats = loaded.base_stats
    original_facts = loaded.events[0].facts
    original_lineup = loaded.events[0].lineup

``items`` supplies possession groups and period-local previous/next links;
``events`` supplies the native enhanced events in original order.
``counts_by_team`` counts credited possessions, which can differ from the
number of groups. ``base_stats`` contains the shared player/lineup possession
and playing-time records, including second-chance, penalty, and foul-count
breakdowns. Free-throw possession credit uses the lineup at the associated
foul, even when substitutions occur between attempts.

Clocks retain exact decimal seconds. Canonical display normalizes equivalent
clocks without dropping fractional digits, and event duration subtraction does
not depend on the caller's decimal precision. Consumers aggregating arbitrary
precision durations should also choose sufficient decimal precision.

Detailed ``event_stats``, ``Possession.possession_stats``, and aggregate
``Possessions.player_stats`` raise an explicit error. Their full statistical
evidence contract is not implemented; an unknown foul-drawn identity is never
filled from the free-throw shooter. Use ``base_stats`` for the supported
accounting output. This entry point is not registered as a ``Client`` provider.
WNBA three-point zone lookups require the optional :doc:`v3-shot-zones`
evidence loader. Missing or conflicting evidence raises, including when
``possession_start_type`` depends on that shot. A possession's offense,
boundaries, score, counts, and time accounting remain available without that
optional label.

Evidence and failure behavior
-----------------------------

The loader requires ``StatsNbaV3LineupLoader`` and supports NBA, WNBA, and G League
under the rules described in :doc:`v3-leagues`. Complete roster and PBP declarations, validated period starters, and
batch evidence remain prerequisites from the earlier layers. Every supplied
home/away score is checked against accumulated classified scoring.

Free-throw trips require one compatible, unconsumed, preceding foul at the
same exact clock and period. Attempts must run from 1 through the declared
total with the same shooter, team, category, and clock. A technical attempt
can intervene in a regular trip. Ordinary one-point trips require a matching
and-one; take/away-from-play awards retain the ball, and G League single-shot
trips carry their recorded point value. Other non-shooting regular trips require exhausted team fouls before the
foul. Required but missing trips fail, as do explicitly conflicting shooters.
Take/away-from-play free throws require the shooter to have been on court at
the foul; a subsequent substitution cannot establish that eligibility.
Technical, flagrant, and clear-path attempts do not become ordinary final-shot
possession boundaries.

Rebounds consume a missed shot once. A real defensive rebound ends the
shooting team's possession; an offensive rebound preserves it. Non-live
free-throw, shot-clock, and period-end team placeholders are identified
separately and do not acquire offensive/defensive rebound credit. Unmatched,
repeated, or contradictory evidence fails. Offensive fouls require a matching
turnover; defensive goaltending requires a matching awarded field goal.
An interior jump requires evidence of the preceding offense.

The recorded defensive lane violation between two made attempts in one trip
and a shooter violation following a final missed free throw awarded to the
opponent by a team rebound are accepted; other lane rulings require additional retry/restart evidence and
fail. Replacement-shooter exceptions, offsetting penalties, corrected or
repeated attempts, unusual technical-foul restarts, and other
unvalidated sequences are outside this integration's supported contract.
Back-to-back offense groups also fail instead of receiving an implicit
restart override. A recognized event label alone does not establish its
restart meaning. See the NBA's `free-throw rules
<https://official.nba.com/rule-no-9-free-throws-and-penalties/>`_ and
`foul rules <https://official.nba.com/rule-no-12-fouls-and-penalties/>`_ for
the underlying distinctions; this adapter is not a complete rules interpreter.

Recorded validation
-------------------

The 2019 Pelicans-Raptors game runs through the production box-score, raw PBP,
participant, classification, lineup, and possession loaders with network
connections disabled. All 573 classified events are retained. The 227 group
boundaries, period numbers, offense teams, and starting score margins match
the paired V2 fixture, and scoring reconciles to 130-122.

Credited counts are Toronto 114 and New Orleans 112. The two additional
Toronto credits relative to V2 occur at the ends of Q1 and Q3: the native V3
possessions start with 2.8 and 2.1 seconds left, while the paired V2 rows show
2 seconds. The shared engine excludes certain non-scoring possessions that
start with at most 2 seconds left. This is the library's counting convention,
not an NBA rule; exact V3 clocks correctly fall on the other side of that
threshold.

Playing time totals 265 minutes per team, every player's time agrees with the
reviewed published box score within half a second, and all DNPs have zero
time. Synthetic cases separately exercise missing and conflicting evidence,
and-one and technical trips, retained-ball attempts, substitutions during
trips, held balls, exact fractional thresholds, and one-possession periods
through overtime. These checks establish the covered fixture and cases,
not universal NBA feed coverage.

The :doc:`v3-leagues` validation matrix adds current NBA, WNBA, and G League
captures, team heaves, separately sourced bench technicals, and reviewed
already-applied replay corrections.
