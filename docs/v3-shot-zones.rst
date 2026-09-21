V3 three-point zone evidence
============================

``StatsNbaV3ShotZoneLoader`` joins a separately recorded official live PBP
response to classified native V3 events. It exposes the provider's reported
``Corner3`` and ``Arc3`` labels when the sources agree. It does not derive a
WNBA corner boundary from NBA coordinates or establish geometric ground truth.
The same API uses the classified game's NBA, WNBA, or G League context.

Usage
-----

Given ``events`` from ``StatsNbaV3EventLoader`` and ``lineups`` constructed
from those events with separately validated period starters::

    from pbpstats.data_loader.stats_nba_v3.shot_zones import (
        StatsNbaV3ShotZoneLoader, V3LiveShotEvidence,
    )
    from pbpstats.data_loader.stats_nba_v3.possessions import (
        StatsNbaV3PossessionLoader,
    )

    source = V3LiveShotEvidence.from_file("recorded-live-pbp.json")
    zones = StatsNbaV3ShotZoneLoader(events, source)
    for result in zones.items:
        print(result.source_index, result.action_number,
              result.shot_type, result.issues)

    loaded = StatsNbaV3PossessionLoader(lineups, shot_zones=zones)
    # Each dependent lookup requires valid evidence for that shot.
    # To reject any unresolved three-pointer before consuming labels:
    zones.require_complete()

``V3LiveShotEvidence(raw_bytes, source)`` also accepts recorded bytes directly.
``source_bytes``, ``sha256``, and ``source`` retain exact input and provenance;
``data`` returns a defensive copy. ``from_file`` defaults the source label to
the file path and optionally accepts ``source=`` with the recorded origin URL.
Provenance is a caller assertion, not authenticated proof of origin. Loading
never accesses the network or writes a cache. Missing files retain
``FileNotFoundError``; malformed JSON, duplicate JSON keys, and non-finite
numbers are rejected with the source location.

Validation and limits
---------------------

Game ID and unique ``actionNumber`` identify each candidate. Its period,
clock, player, team, field-goal flag, three-point action type, made/missed
result, and both finite legacy coordinates must agree with native V3. Equivalent
clock spellings compare equal; the bounded untimed-overtime exception below
allows distinct clock representations. Coordinates have no rounding tolerance. The
source's ``area`` and ``areaDetail`` must map to the same supported zone and,
for corners, the same side. Supported areas are ``Left Corner 3``,
``Right Corner 3``, and ``Above the Break 3``. Details accept those labels or
the recorded NBA/G League ``24+ Left``, ``24+ Right``, ``24+ Center``,
``24+ Left Center``, and ``24+ Right Center`` vocabulary. Unknown labels fail
dependent access instead of receiving a default zone.

``items`` contains one immutable result per represented native three-pointer.
``by_source_index`` indexes the same results by the native row index, which
is distinct from ``actionNumber``. Each result retains both labels, a
``validated`` boolean, ``shot_type`` (``None`` on failure), and explicit
``issues``. ``native_clock`` and ``live_clock`` retain their original strings;
``clock_basis`` identifies ``exact`` or ``untimed_sequence`` agreement and is
``None`` when clock evidence fails. A clock match alone cannot validate a zone
with conflicting identities, coordinates, or labels.
``require_zone(source_index)`` raises for missing or unresolved
evidence; ``require_complete()`` checks every represented three-pointer, not
whether the input covers a full game. Duplicate action numbers, an unrelated
game, or extraneous live three-point rows fail at construction.

Context and snapshot fingerprints prevent attaching the result to different
lineup inputs. With ``shot_zones=`` supplied, unresolved shots never fall back
to a coordinate threshold, including in NBA and G League games. Without that
argument, existing NBA/G League behavior remains, and WNBA three-point lookups
still require evidence. Validated labels also enable dependent
``possession_start_type`` make/miss/block labels. Conflicting labels do not
prevent scores, possession counts, or ``base_stats`` time accounting.
Two-point zones, team heaves, full detailed event statistics, starter evidence,
and replay corrections are outside this additional evidence contract.

Untimed G League overtime
-------------------------

The `2025-26 G League rules
<https://gleague.nba.com/gleague-playing-rules>`_ specify untimed overtime with
a target seven points above the tied regulation score. The recorded live
feed explicitly marks this period with ``periodType="OVERTIME"`` and
``isTargetScoreLastPeriod=true``, using zero clocks throughout. Native V3
instead retains a descending counter starting at 99:00.

For G League seasons starting in 2022 or later, a first-overtime clock
mismatch can use ``clock_basis="untimed_sequence"`` only if all of the
following evidence agrees:

* Native snapshot completeness is declared, every live row identifies a
  valid period, and neither source has a later overtime period.
* Every live overtime row has the explicit metadata and a zero clock.
* Both sources contain matching start/end action numbers, a tied opening
  score, and an agreeing final score. Native clocks start at 99:00 and never
  increase.
* Every field-goal and free-throw attempt, including misses, appears in the
  same order between those boundaries, with matching action number, player,
  team, shot value/type, field-goal flag, and outcome.
* The accumulated native scoring agrees with each live attempt's home/away
  score and any native score supplied on those attempts. The target is first reached on the
  last attempt, at the native period-ending clock.

Missing or contradictory corroboration retains the clock error, with a
reason identifying the failed period or scoring evidence. Individual shot
identity, coordinate and zone-label checks still apply. This comparison
does not derive elapsed time from the live zero clock, change native clocks,
infer lineups, resolve replays, or replace possession validation. Timed NBA,
WNBA, earlier G League overtime, and regulation periods keep exact-clock
comparison.

Recorded findings
-----------------

``tests/data/v3/shot_zones/manifest.json`` records the official origin URLs,
September 21, 2026 capture times, and SHA-256 checksums of four unmodified live
responses. They join the native fixtures documented in :doc:`v3-leagues`.

.. list-table::
   :header-rows: 1

   * - Game
     - Accepted / three-point attempts
     - Remaining evidence issues
   * - NBA 0022500341
     - 69 / 69
     - None
   * - WNBA 1022600100
     - 40 / 69
     - 29 conflicting or unsupported label pairs; one also differs in xLegacy
   * - WNBA 1022600101
     - 41 / 51
     - 10 conflicting or unsupported label pairs
   * - G League 2022500001
     - 61 / 61
     - Two overtime attempts use corroborated untimed clock joins

For example, WNBA action 127 in game 1022600100 has ``area="Above the Break 3"``
and ``areaDetail="Left Corner 3"``. Action 403 records xLegacy 80 in live and
81 in native V3. G League overtime actions 737 and 746 have a zero live clock
while native V3 retains its descending elapsed-time counter. Matching period
boundaries and the full twelve-attempt scoring sequence corroborate these
two joins; all possession start labels are available for this G League game.
The WNBA conflicts remain unresolved, and all original labels and clocks
remain intact. The official WNBA ``shotchartdetail`` endpoint timed out during capture, so no
second shot-chart source resolves the label disagreements in this PR.
Agreement is bounded to these provider snapshots, not an independent video
audit or a claim of complete season coverage.
