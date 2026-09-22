Loading a complete V3 game offline
==================================

``load_game`` connects the existing box-score, participant, classification,
lineup, possession, and optional shot-zone validators through one entry point.
NBA, WNBA, and G League use the same API. No network requests, cache writes,
starter inference, source repairs, or provider fallbacks occur.

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
and possessions. The jump_balls stage reads the supplied files; conflicting
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
