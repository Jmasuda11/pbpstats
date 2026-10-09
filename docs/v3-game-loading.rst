Loading a complete V3 game offline
==================================

``load_game`` connects the existing box-score, participant, classification,
lineup, possession, and optional shot-zone validators through one entry point.
NBA, WNBA, and G League use the same API. No network requests, cache writes,
starter inference, raw-source edits, or provider fallbacks occur. The optional
V2-derived mode below can repair bounded cases in the derived processing order.

.. code-block:: python

    from pbpstats.data_loader.stats_nba_v3.game import load_game, V3GameLoadError

    try:
        game = load_game(
            "1022600101", "recorded-game", league_id="10",
            snapshot_complete=True,
            # Optional; defaults to lineups.evidence.json:
            lineup_evidence="lineups.evidence.json",
            # Optional, separately captured official live response:
            shot_evidence="live-pbp.json",
        )
    except V3GameLoadError as error:
        print(error.game_id, error.diagnostic.stage,
              error.diagnostic.code, error.diagnostic.message)
        raise

    print(game.possessions.counts_by_team)
    print(game.possessions.base_stats)
    for possession, start_type in zip(
        game.possessions.items, game.possession_start_types
    ):
        print(possession.period, possession.offense_team_id, start_type)
    for diagnostic in game.diagnostics:
        print(diagnostic.stage, diagnostic.source_indices,
              diagnostic.possession_index, diagnostic.message)

Only declare ``snapshot_complete=True`` after verifying complete PBP coverage.
The declaration is required independently of the complete roster and reviewed
period starters. Omitting it, passing a non-boolean truthy value, or supplying a
league inconsistent with the game ID fails before files are read. Supported
league/season formats are described in :doc:`v3-leagues`.

Bundle layout and provenance
----------------------------

For importing recorded responses and preparing reviewed lineup evidence, see
:doc:`v3-evidence-preparation`.

The data directory contains ``pbp/stats_v3_<game_id>.json``,
``game_details/stats_v3_boxscore_<game_id>.json``, its matching
``.evidence.json`` sidecar, and the reviewed lineup evidence. Explicit evidence
paths may be absolute; relative paths resolve under this directory. Omitted
shot evidence is not searched for automatically. Blank team-recovery jumps
can use an explicit pair of ``jump_ball_evidence="jump-balls.evidence.json"``
and ``jump_ball_live="pbp/live_<game_id>.json"`` arguments. Both are required
together and retained in ``game.inputs``. See :doc:`v3-reliability` for the
reviewed join contract; source rows are never rewritten.

The box-score source labels are the canonical relative ``game_details/...``
paths. Consequently lineup fingerprints remain valid when the bundle moves
to another machine or directory. Existing evidence built with different
provenance labels must be reviewed and regenerated against these inputs;
the loader never rewrites or silently updates fingerprints.
``game.inputs`` records each actual absolute input path and the SHA-256 of
the bytes used. Each underlying loader also retains its source data.

Results and failures
--------------------

``V3Game`` exposes ``boxscore``, ``pbp``, ``classified``, ``lineups``,
``possessions``, and optional ``shot_zones`` for inspection. The returned
``capabilities`` and ``inputs`` mappings are read-only. ``diagnostics`` and
``possession_start_types`` are tuples.

Required failures raise ``V3GameLoadError`` (a ``ValueError``) with a game ID,
stage, code and original message. The original exception remains available
as ``__cause__``, including ``FileNotFoundError``. Stages are configuration,
boxscore, pbp, jump_balls, participants, classification, lineups, shot_zones,
possessions, and scoring (when V2-derived rules are enabled). The jump_balls stage reads the supplied files; conflicting
joins fail in participants.
The first required failure stops loading; no partial core result is returned.
An explicitly supplied unreadable or structurally invalid shot file also
fails, rather than silently falling back to coordinates.

Unresolved individual shot zones do not discard otherwise valid core results.
Their row indices appear in diagnostics. ``possession_start_types`` aligns
with ``possessions.items`` using zero-based indices; an unavailable label is
``None`` with a diagnostic carrying its ``possession_index``. The underlying
strict ``possession.possession_start_type`` property still raises on that
label. Missing WNBA shot evidence likewise leaves core results usable.
Without supplied shot evidence, existing NBA/G League coordinate-based label
behavior remains; ``shot_zone_evidence="not_supplied"`` makes that distinction
explicit. See :doc:`v3-shot-zones` for the supported evidence contract.

Core possessions, lineups, and base statistics are marked ``complete`` on a
successful return, meaning they passed the current validators for the supplied
snapshot. This does not authenticate completeness declarations or establish
universal game coverage. Detailed event statistics remain ``unavailable`` and
are reported explicitly; this entry point does not register a full V3
``Client`` possession provider. Ten recorded full games exercise this API,
including directory relocation and offline loading with optional-label gaps.

V2-derived processing rules
--------------------------

Both ``prepare_game`` and ``load_game`` accept ``use_v2_rules=True``. The default
remains the original strict mode. Enable the option in both calls; generated
lineup evidence records ``processing_rules: v2`` and cannot be loaded silently
in strict mode. Existing reviewed starter and batch records remain supported.

The adaptations come from the legacy V2 implementation:

* ``NbaEnhancedPbpLoader._add_extra_attrs_to_all_events``: accumulate made-shot
  and free-throw points. Conflicting source score annotations become
  ``stale_score_annotation`` diagnostics. High-level preparation/loading
  requires both team and player point totals to match the box score, including
  explicit zero-minute evidence for players with missing scoring statistics.
* V2 replay events: process the caller-declared final snapshot and retain replay
  events. Unreviewed overturn rows produce ``final_snapshot_replay`` notices
  instead of an approval requirement. No reversal is synthesized. Supplied
  replay review records still undergo their original validation.
* ``Substitution.current_players``: prepare individual transitions in source
  order, including leave/re-enter chains. Outgoing/incoming eligibility, five
  players per team and published-minute reconciliation remain required.
  Explicitly reviewed atomic batches are preserved.
* ``_fix_order_when_technical_foul_before_period_start``: process opening-clock
  technical activity after its unique period-start marker. Bounded V3
  extensions support an OT opening jump and a zero-clock team-heave/rebound
  pair after the closing marker. Repairs change derived processing order only;
  raw bytes, row indices and semantic input fingerprints remain unchanged.
* ``FreeThrow.foul_that_led_to_ft``: search compatible same-clock fouls before,
  then after a trip. Keep unique foul matching, team, on-court and award checks. Numbered
  technical trips require matching individual technical foul awards; same-clock
  administrative technical activity may accompany an ejection before the
  explicit replacement, but later participation remains invalid.
* V2 ``FieldGoal`` basket/FT linkage: a unique same-team basket and a one-shot
  award can belong to different recorded players. A personal or loose-ball foul
  at the basket's clock can support the NBA one-shot award without bonus status.
  The recorded FT shooter is kept separate from both scorer and fouled player.
  A same-team shooter change during a trip preserves attempt numbering and the
  linked foul. These patterns do not establish an injury diagnosis or fill a
  missing ``foul_drawn`` role from the FT shooter.
* V2 ``Violation`` is passive: a lane marker with FT/lane-turnover context does
  not itself create a possession boundary or imply an extra FT attempt. Keep
  recorded FT, rebound and turnover outcomes across timeouts, subs and replays.
  A same-clock shooting-team turnover can end a regular trip before its final
  attempt; preserve the original numbering and only the attempts actually
  recorded, including when the turnover's cause is unspecified. Opposing-team
  turnovers, incomplete trips without an explicit ending and contradictory
  attempts still fail. Double-lane jumps retain their separate validation.
* V2 jump possession rules need the winning team, not both jumpers' identities.
  Preserve the explicit actor and any unknown opponent. If all on-court tip
  candidates share a team, that team can be used while the recipient remains
  ambiguous. The actor's ID/team alone never establishes the winner. For blank
  jumps or ambiguous recipients on opposing teams, bounded look-ahead can infer
  the recovering team from the next supported control event; see
  :doc:`v3-lineups`. Individual identities remain unresolved/ambiguous, with an
  ``implied_jump_winner`` diagnostic and source-row provenance.

The V3 classifier also recognizes numbered technical FT descriptions and an
explicit turnover with an empty subtype. The latter counts as a turnover with
an unspecified cause, never as V2 numeric action type zero (``is_no_turnover``).

Preparation reports separate non-blocking ``notices`` from blocking
``diagnostics``. Loaded games expose these notices through ``diagnostics`` and
record the selected mode in ``capabilities.processing_rules``. Low-level
``StatsNbaV3LineupLoader`` accepts the same option and the possession loader
inherits it; these low-level objects alone cannot reconcile a box score. Use
``load_game`` for that guarantee and retain importer checks of other player
statistics and minutes before publication.

The mode does not infer absent jump identities, choose among ambiguous names,
add outside-roster participants, invent missing FT attempts, or copy V2's
unmatched-FT category defaults. It also does not fetch a secondary provider or
rewrite cached recordings. Detailed event stats remain unavailable; the shared
V2 possession rules and validated V3 ``base_stats`` continue to be used.

See :doc:`v3-season-2025-validation` for the cached-season audit, regression
results and remaining limitations.
