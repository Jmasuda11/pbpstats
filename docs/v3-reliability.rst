V3 reliability evidence
=======================

Five formerly rejected 2025-26 NBA and 2026 WNBA captures now pass the complete
offline pipeline, bringing full-game coverage to ten games including the
2019 NBA baseline and the existing G League target-score overtime fixture.
All successful games reconcile published player box-score totals, player
minutes within half a second, and cumulative period scores. This remains a
bounded fixture matrix, not validation of every game in a season.

Reviewed team jump recoveries
-----------------------------

Three native snapshots have blank jump descriptions. Their separately
captured official live responses explicitly identify both jumpers and a
recovering team, without an individual recipient. The optional
``V3JumpBallEvidence`` joins these facts without modifying native bytes::

    from pbpstats.data_loader.stats_nba_v3.game import load_game

    game = load_game(
        "0022500340", "recorded-game", snapshot_complete=True,
        jump_ball_evidence="jump-balls.evidence.json",
        jump_ball_live="pbp/live_0022500340.json",
    )

``prepare_game`` accepts the same two arguments. Both paths must be supplied
together; neither file is discovered automatically. The review JSON contains
``schema_version=1``, ``game_id``, ``pbp_sha256``, ``live_sha256``, nonempty
``source``, and a nonempty ``jumps`` array. Each entry contains zero-based
``source_index`` and ``live_source_index``, ``clock_basis``, and its own
nonempty ``source`` explanation. Hashes bind the exact original bytes.

Each join requires a unique matching action number, period, recovered-jump
kind, opposing roster players, supported player names, and agreement with
the native actor. A team recovery requires explicit ``personId=0``, matching
``teamId`` and ``possession``, a ``Team (<tricode>)`` recovery name, no
individual recovery ID, and a player filter containing exactly both jumpers.
The recipient has status ``team`` and no player ID; ``require_player`` still
raises for it, and no ``player2_id`` is invented. The winning jumper is not
assumed to be the recipient.

``clock_basis="exact"`` accepts a held-ball recovery at exactly the native
clock. ``"opening_recovery"`` supports the observed first-quarter opening
tip/recovery distinction: both jumps must immediately follow the first
period start, the native clock must equal the opening clock, the live
descriptor must be ``startperiod``, and the live recovery must precede the
same next field goal with matching clock, player, team and result. Scores
must still be zero. This is not a general clock tolerance or a join for
arbitrary missing events. Other cases remain unsupported.

Missing, stale, duplicate or conflicting joins fail explicitly. Changing
either evidence file changes the provenance bound into lineup fingerprints.
Source labels are review assertions, not authentication of a capture.
Complete rosters and these jump joins do not establish later-period starters.

Other recorded cases
--------------------

Separate bench-person evidence now identifies Mark Daigneault, Jamahl Mosley
and Rachid Meziane in their recorded games. Native technical IDs and names
are corroborated by matching action number, period, clock and ID in the
official live capture, which supplies the team. These identities never enter
the roster or starter witnesses. Missing bench evidence still rejects them.

Recorded five-second turnovers and hanging technicals are classified.
Hanging technicals do not add personal or team penalty fouls. A recorded
player ejection requires explicit replacement before play resumes; the
loader never removes a player automatically, permits re-entry, or uses an
ejection as starter evidence. Coach ejections remain unsupported.

A team rebound can no longer consume a same-clock shot-clock turnover
across an intervening shot or control event. In Rockets-Thunder's second
overtime, native rebound 576 is real and rebound 579 is the placeholder
associated with turnover 580. Duplicate or reused placeholders still fail.

Reviewed substitution batches are supported by explicit outgoing/incoming
pairs in uninterrupted live substitution runs, with full native stream
coverage. Replay reviews assert outcomes already present in the final
snapshot and retain affected native rows; they do not edit source events.
Oklahoma City's otherwise quiet first-overtime starter Isaiah Hartenstein
has a separate live entrance before the period start and a foul-drawn witness
after it, with no intervening substitution. The roster alone is insufficient.

Remaining failures
------------------

* ``0022500165`` (Bucks-Raptors): jump and turnover rows 25-27 conflict about
  control. The live response also retains conflicting tip/possession facts;
  no restart override is applied.
* ``1022600061`` (Sparks-Sun): native row 297 records an ordinary one-shot
  free throw after a teammate's made three and a loose-ball foul. The current
  award/restart contract cannot validate that sequence. Its
  ``lineups.review.json`` records reviewed lineups and minutes, but possession
  loading fails and ``prepare_game`` refuses to publish approved evidence.

Detailed event statistics and full V3 ``Client`` integration remain separate
work. See :doc:`v3-leagues` for the coverage matrix and source provenance.
