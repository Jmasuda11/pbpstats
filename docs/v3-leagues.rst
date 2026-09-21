V3 league selection and recorded validation
===========================================

The native V3 pipeline accepts ``league_id="00"`` (NBA), ``"10"`` (WNBA),
or ``"20"`` (G League). Omitting it selects the game ID's league prefix.
An explicit mismatch fails before reading source files. The season comes
from the game ID, so the 2025-26 NBA/G League season uses ``25`` and the
2026 WNBA season uses ``26``. Regular-season and playoff IDs are supported;
other formats, including Showcase events, require separate rules validation.

The same offline entry points serve all three leagues::

    from pbpstats.data_loader.stats_nba_v3.boxscore import (
        StatsNbaV3BoxscoreFileLoader, StatsNbaV3BoxscoreLoader,
    )
    from pbpstats.data_loader.stats_nba_v3.pbp import (
        StatsNbaV3PbpFileLoader, StatsNbaV3PbpLoader,
    )
    from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
    from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
    from pbpstats.data_loader.stats_nba_v3.lineups import StatsNbaV3LineupLoader, V3LineupEvidence
    from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader

    league_id, game_id = "10", "1022600100"
    directory = "my-recorded-data"
    box = StatsNbaV3BoxscoreLoader(
        game_id, StatsNbaV3BoxscoreFileLoader(directory, league_id=league_id),
        league_id=league_id,
    )
    raw = StatsNbaV3PbpLoader(
        game_id, StatsNbaV3PbpFileLoader(directory, league_id=league_id),
        league_id=league_id,
    )
    participants = StatsNbaV3ParticipantLoader(
        raw, box.require_complete_roster(), snapshot_complete=True,
    )
    facts = StatsNbaV3EventLoader(participants)
    evidence = V3LineupEvidence.from_file("my-reviewed-lineups.json")
    lineups = StatsNbaV3LineupLoader(facts, evidence)
    possessions = StatsNbaV3PossessionLoader(lineups)

Only declare ``snapshot_complete=True`` after reviewing full-game coverage.
The context and snapshot fingerprints in the lineup evidence must match the
actual inputs, including their provenance. Computing these hashes does not
prove starters or substitution batches. See :doc:`v3-lineups`.

League rules
------------

``V3LeagueRules`` supplies period lengths, free-throw format, and foul limits
to the native adapters. NBA and G League regulation quarters use 12 minutes;
WNBA quarters use 10. NBA and WNBA overtime uses five minutes. Pre-2006 WNBA
halves are rejected. See the `2026 WNBA rule book
<https://cdn.wnba.com/sites/4/2026/05/2026-WNBA-Official-Rule-Book.pdf>`_.

G League ordinary single-shot free throws from 2019-20 carry one, two, or
three points per physical attempt, except in the final two minutes of Q4
and in overtime. From 2022-23, overtime ends when a team reaches the tied
regulation score plus seven. The captured native feed uses a descending
99:00 counter: its differences measure recorded elapsed play, not a 99-minute
period. Validation requires a regulation tie, one overtime period, and an
immediate ending after the winning field goal or terminal free throw; the
end marker adds no extra possession credit. Untimed overtime has no last-two-
minutes foul adjustment. See the `G League experimental rules
<https://gleague.nba.com/gleague-playing-rules>`_.

Recognized transition-take and away-from-play awards retain the ball after
one free throw. Personal-take fouls use ordinary bonus validation. Defensive
three-second technical attempts retain the interrupted offense. Native team
heaves retain a team miss with no invented player or shot value, with
league/season/period checks. Detailed event statistics and full ``Client``
possession-provider registration remain outside this adapter's contract.
Take/away-from-play shooters must belong to the lineup at the foul. WNBA
corner/arc three-point classification also remains unvalidated, so its lookup
and dependent ``possession_start_type`` labels raise explicitly; this does not
prevent possession counts or lineup/time accounting.
Transition-take awards exclude the last two minutes of Q4 and timed NBA/WNBA
overtime, and the entirety of G League overtime; see Rule 4 in the
`2025-26 NBA rule book
<https://cdn.nba.com/manage/2026/01/Official-2025-26-NBA-Playing-Rules.pdf>`_.

Separate bench and replay evidence
----------------------------------

A full player roster cannot identify a coach. The box-score sidecar optionally
accepts ``bench_people`` records with positive ``person_id``, game ``team_id``,
``name``, and nonempty ``source``. These create immutable ``V3BenchPerson``
identities, never roster players or starter candidates. Their only supported
use is a technical foul whose explicit ID and description agree; team
conflicts, duplicate IDs, player/bench overlap, and other event roles fail.
Missing bench evidence still rejects an outside-roster ID.

Changed replay labels are classified as recorded facts. The possession layer
additionally requires ``resolved_replays`` in the fingerprint-bound lineup
sidecar. Each entry identifies a changed replay's primary ``source_index``,
nonempty ``affected_source_indices``, nonempty ``source`` provenance, and
``resolution="already_applied"``. Every changed replay must appear exactly
once. This is a caller's reviewed assertion that the final snapshot already
contains the corrected outcome; it neither authenticates a video ruling nor
authorizes row edits. Missing, stale, duplicate, or conflicting evidence fails.
Replay support does not enable arbitrary live-feed correction processing.

Recorded coverage
-----------------

``tests/data/v3/leagues/manifest.json`` records eleven final official captures
retrieved on September 21, 2026. NBA and WNBA fixtures are intact native
``playByPlay`` objects and team arrays extracted from official game pages'
``__NEXT_DATA__``. Their envelopes are explicitly labeled page extracts.
G League fixtures preserve original Stats V3 endpoint response bytes.
URLs, capture times, raw capture hashes, extraction methods, and committed
file hashes distinguish these sources. No test-only player pool is used.

Four full games pass the complete pipeline with networking disabled:

.. list-table::
   :header-rows: 1

   * - Game ID / local game date
     - Matchup and final score
     - Possession groups / credited away-home
   * - 0022500341 / December 5, 2025
     - Spurs 117, Cavaliers 130
     - 207 / 102-102
   * - 1022600100 / June 13, 2026
     - Sparks 111, Mercury 102 (OT)
     - 177 / 88-87
   * - 1022600101 / June 14, 2026
     - Mystics 64, Liberty 86
     - 157 / 78-77
   * - 2022500001 / December 19, 2025
     - Stockton 119, Austin 117 (target OT)
     - 214 / 106-105

For these games, independent published player totals reconcile for points,
field goals, threes, physical free throws, assists, blocks, steals, turnovers,
rebounds, and personal fouls. Every player's minutes agree within 0.5 seconds,
including zero minutes for DNPs; every period's cumulative team score agrees.
Possession counts are regression expectations for the shared engine's
counting convention, not independently published official possession counts.

Q1 starters agree with box-score position markers. Every later period has
separate on-court witnesses before an entrance in the reviewed substitution
stream. Stockton's otherwise unobserved fifth overtime starter, Daeqwon
Plowden, is uniquely established by published full-game minutes minus
validated regulation minutes: exactly five players have 153 seconds left,
all others have zero within rounding tolerance, and Stockton makes no OT
substitutions. The production loader performs no starter inference.

Seven additional captures preserve rejection cases:

* 0022500165 (Bucks-Raptors): roster, points, and minutes reconcile, but jump
  and turnover rows 25-27 need separate control/restart evidence.
* 0022500340 (Nuggets-Hawks), 0022500001 (Rockets-Thunder), and 1022600001
  (Sun-Liberty): blank jump descriptions leave required participants unresolved.
* 0042500317 (Spurs-Thunder), 0022500166 (Magic-Hawks), and 1022600061
  (Sparks-Sun): coach technical IDs lack separately supplied bench evidence.

These are bounded compatibility tests, not a claim of complete season
coverage. Other lane rulings, replacement shooters, offsetting penalties,
truncated winning free-throw trips, and unsupported corrections still fail
until their evidence and restart contracts are validated.
