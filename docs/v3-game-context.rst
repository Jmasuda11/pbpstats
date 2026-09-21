V3 box-score evidence and game context
======================================

``StatsNbaV3BoxscoreLoader`` builds the participant resolver's ``V3GameContext``
from a native Stats ``boxScoreTraditional`` response and an explicit evidence
sidecar. Loading is offline. Missing files raise ``FileNotFoundError``;
malformed or conflicting evidence raises ``ValueError`` with the game and
source locations. No roster, alias, or network fallback runs implicitly.

This API is a direct context loader. It is not registered as a statistical
``Client`` Boxscore resource: statistics remain raw, unvalidated source fields.

Fixture inspection and supported contract
-----------------------------------------

The contract was chosen after inspecting the available inputs:

* Repository Stats box-score fixtures are V2 tables. A separate V2 summary
  provides home/away identity. A range box score contains only a time interval;
  its player rows cannot establish a complete game roster.
* The repository live box score is a different provider schema.
* The earlier local experiment contains an enriched PBP ``roster`` list, but no
  native V3 box-score fixture. That list does not establish its capture source,
  home/away identity, eligible-player completeness, or alias coverage.
* The pinned `nba_api traditional V3 response
  <https://raw.githubusercontent.com/swar/nba_api/0d0108875f3fc9455f67cbd6670aeb642756009f/docs/nba_api/stats/endpoints/responses/boxscoretraditionalv3.json>`_
  for ``0022500165`` contains root and nested home/away IDs, 14 home players,
  15 away players, full-name components, and ``nameI``. Two players have DNP
  comments and empty minutes. The two Antetokounmpos demonstrate why a surname
  must retain multiple candidates. Suffixes occur in ``familyName`` and ``nameI``.

The recorded response is copied byte for byte. Its checksum, immutable source,
retrieval time, and response metadata time are recorded separately in
``tests/data/v3/boxscore-manifest.json``. A response metadata time is not an
independently verified capture time. This fixture's original request range and
eligible-player coverage are unverified, so its evidence declares
``scope="unknown"`` and ``roster_complete=false``.

For ``0021900001``, a separately reviewed `NBA.com box-score page
<https://www.nba.com/game/nop-vs-tor-0021900001/box-score>`_ now supplies the
matching active roster, including all six DNPs. The committed DOM observation
and its explicit projection into the supported box-score shape are labeled
page-derived evidence, not a captured API response. Both files are checksum
bound. The full-game participant tests use this validated 26-player context.
The ``0022400001`` participant test still uses an explicitly test-only pool.
See :doc:`v3-lineups` for separate period-starter validation.

Offline usage
-------------

Place both files under the data directory:

.. code-block:: text

    game_details/stats_v3_boxscore_0022500165.json
    game_details/stats_v3_boxscore_0022500165.evidence.json

.. code-block:: python

    from pbpstats.data_loader.stats_nba_v3.boxscore import (
        StatsNbaV3BoxscoreFileLoader,
        StatsNbaV3BoxscoreLoader,
    )

    box = StatsNbaV3BoxscoreLoader(
        "0022500165", StatsNbaV3BoxscoreFileLoader("tests/data")
    )
    context = box.context
    print(context.team_ids)
    print(context.player(202066).name)  # Garrett Temple, retained despite DNP
    print(context.candidates("Antetokounmpo", 1610612749))  # Two candidates

Pass ``box.context`` to ``StatsNbaV3ParticipantLoader(raw, context)`` for the
same game. If the caller requires complete coverage, use
``box.require_complete_roster()``; it raises for the recorded example above.
An incomplete context still provides roster membership for known explicit IDs,
but the participant resolver leaves description-only identities unresolved.

Custom sources implement ``load_data(game_id)`` and return
``V3BoxscoreSourceData(boxscore_bytes, evidence_bytes, boxscore_source,
evidence_source)``. Exact bytes are decoded by the loader itself, avoiding
disagreement between a supplied decoded payload and its claimed checksum.
``box.source`` retains these immutable bytes and locations. ``source_data`` and
``evidence`` return defensive copies of the decoded inputs, including unknown
fields. ``source_sha256`` and ``evidence_sha256`` fingerprint both inputs.

Evidence sidecar, version 1
---------------------------

The sidecar contains these fields:

``schema_version``
    Integer ``1``.
``game_id``
    The same ten-digit NBA game ID as the request and response.
``boxscore_sha256``
    Lowercase SHA-256 of the exact response bytes, including whitespace.
``source``
    Nonempty provenance description, preferably an immutable source URL or
    a capture record identifying the request and archive. The loader records
    this declaration; it cannot authenticate its truthfulness.
``scope``
    ``full_game``, ``partial``, or ``unknown``. A range response must not be
    declared a full-game roster merely because it includes both teams.
``roster_complete``
    Required boolean. ``true`` is a caller-reviewed declaration of the entire
    game player pool, including players without PBP actions, and the documented
    alias policy. It requires full-game scope, a nonempty completeness basis,
    and at least five distinct players on each team. These structural checks
    can reject contradictions; they cannot prove no player is missing.
``completeness_basis``
    Required nonempty text when complete. Record the evidence supporting the
    coverage decision. A final score, player count, minutes, or observed PBP
    actors alone do not certify completeness. With insufficient evidence, use
    ``roster_complete=false``.
``aliases``
    Optional array of additional naming evidence. Each object needs a positive
    integer ``player_id``, matching ``team_id``, nonempty ``names`` array, and
    nonempty ``source``. Entries must refer to players already in the box score;
    they cannot add players or change team membership.

For example, a reviewed alias entry has this shape (illustrative, not evidence
for a real player):

.. code-block:: json

    {
      "player_id": 123,
      "team_id": 1610612761,
      "names": ["Smith", "A. Smith"],
      "source": "Reviewed archive record documenting these exact name forms"
    }

The response's ``homeTeamId`` and ``awayTeamId`` must be positive, distinct
integer IDs and agree with their corresponding nested ``teamId`` fields. Each
team must contain a ``players`` array. Player IDs must be positive, unique
across both teams, and distinct from team IDs. An optional player ``teamId``
must agree with the containing team. DNP and empty-minute entries are retained.

Name and alias policy
---------------------

Each player requires nonempty ``firstName`` and ``familyName``. The loader
records their combined full name as ``V3RosterPlayer.name`` and indexes the
full name, exact family name, and ``nameI`` when present. A supplied ``nameI``
must be nonempty text; the loader does not synthesize an initial when missing.
Explicit sidecar aliases extend these names and retain their source records.

The context normalizes Unicode, case, and whitespace for comparison. It does
not remove accents, punctuation, suffixes, or initials; split compound surnames;
decode slugs; or perform fuzzy matching. A suffix-free variant therefore needs
explicit alias evidence. Alias collisions are legitimate candidate sets, scoped
by team where appropriate. The participant resolver reports ambiguity instead
of choosing the first match. Extra alias evidence does not make a partial
roster complete.

Boundaries and next PRs
-----------------------

A complete roster does not establish period starters. ``position``, array
order, minutes, and completeness declarations do not create starter sets or
lineups. Neither roster completeness nor this loader establishes complete PBP
snapshot coverage. The latter remains a separate participant-loader argument.

The next stages are event classification, substitution batches and lineup
reconstruction with separately validated period-starter evidence, then
connection to the possession engine. Each stage must reject missing or
conflicting evidence before dependent statistics are computed.
