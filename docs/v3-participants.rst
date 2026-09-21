V3 event association and participant facts
==========================================

``StatsNbaV3ParticipantLoader`` consumes the raw file loader's output and explicit
game context. It associates related source rows and records the participant
identities supported by the evidence. These are intermediate facts, not enhanced
events, lineups, or possessions. No statistics are computed.

Usage
-----

.. code-block:: python

    from pbpstats.data_loader.stats_nba_v3.context import V3GameContext
    from pbpstats.data_loader.stats_nba_v3.participants import (
        StatsNbaV3ParticipantLoader,
    )
    from pbpstats.data_loader.stats_nba_v3.pbp import (
        StatsNbaV3PbpFileLoader,
        StatsNbaV3PbpLoader,
    )

    raw = StatsNbaV3PbpLoader(
        "0021900001", StatsNbaV3PbpFileLoader("tests/data")
    )
    context = V3GameContext(
        game_id="0021900001",
        home_team_id=1610612761,
        away_team_id=1610612740,
    )
    facts = StatsNbaV3ParticipantLoader(raw, context)
    event = facts.items[0]
    print(event.group.source_indices)
    print(event.participants["actor"].status)

This example supplies no roster, so explicit source identities can be retained
while description-only names stay unresolved. Nothing is fetched implicitly.

To resolve names, supply ``players`` as a sequence of
``V3RosterPlayer(player_id, team_id, aliases)`` objects. Aliases must come from
validated game-roster evidence and cover the forms used in the feed, including
surnames, initials, and any suffix variants. Set ``roster_complete=True`` only
when the eligible player pool and its alias coverage are complete, and record
the evidence in ``roster_source``. A list of actors observed in PBP alone is not
a complete roster: a player can enter without generating an explicit actor row.

The :doc:`v3-game-context` loader builds this context from offline traditional
V3 box-score evidence, preserving player names, provenance, and an explicit
completeness declaration. Roster completeness never establishes period starters.

The context validates game/team identities, duplicate players, and roster team
membership. It cannot independently certify the caller's provenance declaration.
``facts.context`` retains that context for inspection.

Association
-----------

Every accepted raw row belongs to exactly one group. An action number is only
an association candidate within the current snapshot. A group must have one
typed primary action, consistent period and exact clock values, and at most one
recognized secondary row for each role. A steal requires a turnover primary;
a block requires a missed-shot primary. Participant validation also requires
the secondary player to belong to the opposing team.

Output groups follow primary source order. Each group's ``rows`` retain their
original order and ``source_indices`` refer to the raw array. A secondary can
precede its primary; it is still retained at its original position. No raw row
is rewritten, silently deduplicated, or sorted by event number.

Orphan or unknown blank-type rows, conflicting primary actions, repeated
``actionId`` values within one snapshot, and inconsistent contexts produce
errors with game and source-row information. Unknown typed actions remain
visible as groups; this does not mean their basketball semantics are supported.

Participant results
-------------------

Each event has a read-only ``participants`` mapping. Available roles include
``actor``, ``assister``, ``blocker``, ``stealer``, ``outgoing``, ``incoming``,
``opposing_jumper``, ``tip_recipient``, and ``foul_drawn``, according to event type.
Each result includes a status, optional player/team IDs, candidate IDs, source
indices, and resolution evidence.

``explicit``
    A validated source ID identifies the participant.
``resolved``
    The name has one candidate in a declared complete roster and the appropriate
    team context. Jump-ball recipients are checked across both game rosters.
``absent``
    The recorded description or a declared complete snapshot establishes no
    participant in that role.
``not_applicable``
    Individual player attribution does not apply to the recorded role.
``unresolved``
    Required evidence, roster coverage, or identity information is missing.
``ambiguous``
    The complete roster contains multiple candidates for the supplied name.

Name matching normalizes Unicode, case, and whitespace. It does not use fuzzy
matching or silently remove initials, suffixes, accents, or punctuation. A
same-team name collision stays ambiguous. Explicit optional
``assistPersonId``, ``incomingPersonId``, and ``foulDrawnPersonId`` fields, when
provided, take precedence over name matching but must agree with known team and
description evidence. These optional fields are not present in the current
archived Stats V3 fixtures; their handling is covered by synthetic tests.
An incomplete alias pool cannot disprove an explicit identity by omission.

Use ``event.require_player(role)`` before a dependent operation requires an
identified player. It raises for absent, ambiguous, unresolved, and inapplicable
roles. Those states must never be converted to player ID zero or the first
candidate. A missing assister is not automatically an unassisted basket.

Completeness and attribution boundaries
---------------------------------------

``snapshot_complete`` is a separate constructor argument, defaulting to false.
Without that declaration, a missing steal/block row stays unresolved because
an excerpt may have omitted it. Set it to true only with independently established
snapshot coverage; it is not inferred from a final score, row count, or complete
roster. The loader records the declaration but does not prove it.

When ``personId`` contains a known team ID, the event is assigned to that team
without inventing a player. Team ID, roster membership, and home/away location
must agree. Recorded team-heave rows with no player attribution retain that
intentional absence; actual FGA accounting belongs to a later statistics layer.
Replay and period rows are administrative: their ``personId`` must not be treated
as a participating player, even when it is positive or contains a familiar name.

Foul-drawn recovery from free throws is deferred until foul/trip association and
replacement-shooter checks exist. The current layer accepts explicit identities
and otherwise keeps that role unresolved. A shooter at the same clock is not
enough evidence to assign a foul-drawn player.

In the paired 2019 fixture, all 129 recovered secondary identities match V2:
53 assisters, 49 incoming substitutes, 11 stealers, 12 blockers, and four jump-ball
participants. This is a bounded fixture comparison, not a claim of complete
roster acquisition or universal participant/statistical accuracy.
