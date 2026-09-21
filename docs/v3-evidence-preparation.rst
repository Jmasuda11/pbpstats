Preparing V3 game evidence offline
==================================

Use ``import_recordings`` to create a portable bundle from locally captured
native V3 responses, then ``prepare_game`` to identify missing lineup evidence.
Both operate offline and support NBA, WNBA and G League through the same league
parameters as :doc:`v3-game-loading`.

Import recorded files
---------------------

.. code-block:: python

    from pathlib import Path
    from pbpstats.data_loader.stats_nba_v3.bundle import import_recordings

    bundle = import_recordings(
        "1022600101", Path("recorded-game"), league_id="10",
        pbp_file="captures/pbp.json",
        boxscore_file="captures/boxscore.json",
        pbp_source="Official final PBP capture; record its URL and capture details",
        boxscore_source="Official final box-score capture; record its origin",
        roster_complete=True,
        completeness_basis="Both final full-game player arrays retained, including DNPs",
        # Optional independently sourced identity records:
        aliases=[],
        bench_people=[],
    )

The destination must not exist. Input bytes are copied unchanged into the
conventional ``pbp/`` and ``game_details/`` paths after validation. A box-score
evidence sidecar and ``manifest.json`` record origins and SHA-256 checksums.
``imported_at_utc`` records the import time, not an invented retrieval time.
Origins and completeness declarations are caller assertions; the importer
cannot authenticate them. Filesystem failures can leave a partial new bundle;
inspect it before retrying with a new destination.

Inputs must already have the supported native ``game`` and
``boxScoreTraditional`` envelopes. This function does not fetch endpoints or
extract embedded responses from HTML. For official page extracts, describe the
extraction in the source fields rather than claiming an endpoint capture.
See :doc:`v3-game-context` for alias and bench-person evidence schemas.

Only explicit ``personId``/``teamId``-bound ``playerName`` and ``playerNameI``
fields can add automatic aliases for existing roster members. Conflicting
teams fail import; unknown IDs never expand the roster or establish a coach.
Description-only aliases and bench personnel require supplied source evidence.
Ambiguous aliases remain ambiguous in the participant resolver.

``roster_complete`` defaults to false. Setting it to true requires a nonempty
``completeness_basis`` and a structurally valid full-game roster. This does not
declare the PBP complete or identify period starters.

Prepare and review
------------------

.. code-block:: python

    from pbpstats.data_loader.stats_nba_v3.preparation import prepare_game

    preparation = prepare_game(
        "1022600101", bundle, league_id="10",
        snapshot_complete=True,
        substitution_stream_source="Reviewed final all-period PBP and complete substitution coverage",
    )
    preparation.write_report(bundle / "preparation-report.json")
    preparation.write_review_template(bundle / "review.json")
    for diagnostic in preparation.diagnostics:
        print(diagnostic.stage, diagnostic.source_indices, diagnostic.message)

Declare full PBP coverage only after checking it. The additional required
``substitution_stream_source`` names the basis for complete substitution
coverage; starter witnesses depend on that assertion independently of roster
completeness. Neither declaration repairs missing events.

For each period, a resolved on-court participant observed before any incoming
substitution for that player is a starter witness. An outgoing substitution is
also a witness. Technical fouls, technical free throws, replays, timeouts and
period markers do not establish on-court presence. Exactly five box-score
position markers per team can supply **first-period** starters; they are
checked against the witnesses. Other periods require their own witnesses or
explicit starter review. A quiet fifth player is left unresolved: the workflow
never fills from the roster, previous-period lineup, or residual minutes.

Review the generated JSON against the source material, add nonempty ``source``
descriptions, and supply the missing decisions:

* ``periods``: five distinct roster IDs for each team in that period, supported
  independently when automatic witnesses are insufficient.
* ``batches``: explicit membership of adjacent same-clock substitution runs.
  Split proposed runs when the source establishes separate transitions.
  Equal clocks alone do not prove an atomic batch. Isolated substitutions
  between non-substitution or different-clock boundaries can be prepared
  automatically under the complete-stream assertion.
* ``resolved_replays``: a supported final-snapshot resolution and affected row
  indices for each changed replay, following :doc:`v3-possessions`.

All source indices are zero-based primary row positions in the original native
PBP array, not provider action IDs. Generated templates carry game, context and
snapshot fingerprints. Leave the fingerprints unchanged; a mismatch requires
review against the new inputs. Previously reviewed records are retained in
subsequent templates so review can proceed incrementally. Blank sources and
unfilled replay resolutions are not approvals.

Validate and publish
--------------------

After editing the review file with the supported decisions:

.. code-block:: python

    preparation = prepare_game(
        "1022600101", bundle, league_id="10",
        snapshot_complete=True,
        substitution_stream_source="Reviewed final all-period PBP and complete substitution coverage",
        review="review.json",  # Relative to the bundle; absolute paths also work.
    )
    if not preparation.ready:
        raise ValueError(preparation.diagnostics)
    preparation.write_lineups(bundle / "lineups.evidence.json")

    from pbpstats.data_loader.stats_nba_v3.game import load_game

    game = load_game("1022600101", bundle, league_id="10", snapshot_complete=True)
    print(game.possessions.counts_by_team)

Readiness requires complete evidence, successful lineup and possession
validation, and every roster player's reconstructed seconds agreeing with
published minutes within half a second. Supported minutes use ``MM:SS`` with
optional fractional seconds, including the recorded rounded ``:60`` format.
Explicit DNP/DND/NWT labels support zero minutes, either in an otherwise blank
minutes row's comment or in the minutes field itself. Unexplained blanks and
minute conflicts remain blockers; minute totals never choose a starter.

``lineup_candidate`` and ``review_template`` return defensive copies.
``diagnostics`` and the input checksum mapping are read-only. A report can be
written while review is pending, but ``write_lineups`` rejects unresolved
results and rechecks all file inputs, including a supplied review file, before
publishing. All three writer methods create new files exclusively and take
paths relative to the current working directory unless absolute paths are
supplied. They never replace existing evidence. A missing or invalid required
input raises :class:`~pbpstats.data_loader.stats_nba_v3.game.V3GameLoadError`;
unresolved preparation decisions remain visible in the report.

This workflow establishes only the current core validation contract. It does
not authenticate human review, resolve optional shot-zone conflicts, implement
detailed event statistics, or register full V3 possessions in ``Client``.
