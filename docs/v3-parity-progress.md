# V3 parity progress — October 6, 2026

## Where things stand

The adapter decodes V3 rows into the original Stats event classes; the original engine makes every enhancement, possession and attribution decision. Paired 2024-25 V2/V3 season exports now give direct evidence for decoding and a full-game comparison against the original on real games. The October 3 checkpoint is preserved in the linked continuation documents.

All results were executed locally. The branch is pushed to `origin/feat/v3-parity`. The parity workflow's first remote run, on `6ca73ed`, failed at its reference check. The pinned hashes had been computed from Windows (CRLF) checkouts. They now pin committed bytes, and a clone with LF line endings passes every workflow step locally. The upstream `CI` workflow runs the untouched upstream suite under tox. That suite has two known fixture failures, so the workflow cannot pass unchanged.

| Check | Result | Scope |
| --- | --- | --- |
| Untouched original suite against the candidate | 116 pass; the same two known fixture failures | Only the earlier starter I/O split changes an original file |
| Parity tests | 813 pass | Harness, adapter, vocabulary, exceptions, corpus, paired seasons, season differential, WNBA and the fetch tool |
| Paired 2024-25 exports | 574,358 of 574,358 events pair one-to-one; period, actor and team agree on every event | [Paired season evidence](v3-paired-season-evidence.md) |
| Decoder against recorded V2 codes | 188 of 188 labels | Was 156 matching, 8 different and 24 rejected; every table entry is checked |
| Full games, equivalent facts | **937 of 937 comparable games identical** | Floored clocks plus V2 within-instant order; fouled player excluded as a declared gap |
| Full games, V3 order and floored clocks | 565 identical; credited counts equal in all 937 | 69 possessions in 61 games credit a different lineup |
| Full games, exact V3 | Decisions differ in 746 games; +414 credited possessions (+0.22%) | Tenth-of-a-second clocks in final seconds |
| 2025-26 corpus audit | 1,047 research passes; 183 blocked; no crashes | Was 521 on October 5, and 189 in the October 3 document |
| WNBA 2025 paired season | 154 of 154 labels decode to the recorded code; **167 of 167 comparable games identical** with equivalent facts | [WNBA support](v3-wnba-2025.md); three WNBA-only codes |

The season comparison is in [the season differential](v3-season-differential.md); the decoding evidence is in [the paired season evidence](v3-paired-season-evidence.md).

## Changes in this continuation

- **Paired evidence:** vendored the pinned V3 2024-25 export and paired it with the V2 export. Pinned facts are recomputed by `test_paired_season.py`.
- **Decoder codes:** corrected eight codes: Normal Rebound 1, timeouts 1 and 7, Driving Dunk Shot 9, Overturn Ruling 1, Ruling Stands 3, Hanging Technical 13. The rebound code is a decision input: it feeds the original's `is_placeholder`.
- **Decoder vocabulary:** added 24 labels: Replay Center, Altercation Ruling, Ejection, coach-challenge jump balls and 20 foul and turnover subtypes. Removed the unevidenced Official timeout.
- **Actors and double fouls:**
  - Technicals, double technicals and ejections by people outside the player roster (coaches and inactive players) now pass through the recorded `personId`/`teamId` pair, as V2 records it.
  - Double personals and double technicals now decode the second named player, as V2's `PLAYER2` does. A coach as the other party of a double technical has no V3 ID and is recorded as unknown.
- **Tooling:** the research reconciliation reads box-score `MM:60` as one more minute. All 62 games that failed only on that format then reconcile within one second.
- **Season differential:** added `tools/parity/season_differential.py` and its tests.
- **Code review, October 6:**
  - *Adapter:* a source-order repair rebuild now leaves one `starter_recovery` result per period. `recorded_starter_boxscore` entries still log each consumed response, matching the original's repeated requests.
  - *Decoder:* unknown fouls-drawn attribution is recorded only for foul types V2 gives a fouled player. Malformed provenance or JSON is a declared rejection. Roster names match regardless of surrounding whitespace.
  - *Comparison tool:* it separates observation failures from rejections, stops sibling workers when one fails, streams records, and compares double-foul participants.
  - *Tooling:* both tools share one roster-from-actors helper, and the recorded-evidence fixture manifest no longer lists one path with two hashes.
  - Every 2025-26 corpus outcome is unchanged.
- **Fetch, parse and save:**
  - `python -m pbpstats.data_loader.stats_nba_v3.web GAME_ID -o game.json` fetches `playbyplayv3` and `boxscoretraditionalv3`, builds the context from the box score and writes the possessions as JSON. Usage is in [README-PARITY](../README-PARITY.md#fetch-a-game-and-save-possessions-as-json).
  - When starter recovery needs the original's period-start box score, the adapter raises `V3EvidenceRequired` with the exact request. The tool fetches it, records it as evidence and parses again.
  - Offline over the 2025-26 captures, it parses 1,038 games, each with the corpus audit's credited possessions. Live fetches of `0022500089` and `0022500521` also match; the second needed its period-5 box score.
- **WNBA:**
  - The adapter accepts WNBA game IDs, and the fetch tool requests them from `stats.wnba.com`.
  - Three codes recorded only in WNBA data decode for WNBA games alone: official and reset timeouts, and a one-shot clear-path free throw.
  - The paired 2025 exports and the season differential support `--season wnba-2025`.
  - Live, 9 of 12 WNBA 2026 playoff games parse with final scores equal to the box score. The other 3 are rejected for declared reasons.
  - One of the 9 uses a reviewed starter correction. The fetch tool supplies reviewed corrections as `V3Overrides`, bound to the exact play-by-play bytes reviewed.
  - Starter recovery now looks up WNBA override games by integer ID, as the original does.
  - Details are in [WNBA support](v3-wnba-2025.md).
- **CI line endings:** the reference and prior checks now pin each Git tree and the committed bytes of each file. 197 reference and 231 prior file hashes, and one shot-vocabulary source hash, were re-pinned from CRLF to committed bytes. Each old hash was checked against the CRLF extraction that produced it.

## Remaining work

1. **Policy decisions.**
   - *Clock policy: decided October 5, 2026.* The adapter keeps exact V3 clocks. The whole-second floor projection remains only a comparison diagnostic. Measured cost: decisions differ from V2 in 746 of 937 games, and V3 credits 414 more possessions (+0.22%).
   - *Order policy: decided October 6, 2026.* The adapter keeps V3's recorded same-instant order and the original crediting rule, unchanged. Differences from V2's order are treated as V2 recording quality. [The 69 lineup-credit differences](v3-season-differential.md#why-69-possessions-credit-a-different-lineup) are all zero-second substitutions listed on the other side of the possession's crediting event. In 58 of them V3's placement is the plausible one; in 4, V2's was.
   - *Original crash: decided and implemented October 6, 2026.* The original's `Possession.get_team_ids` raises `AttributeError` when it scans a neighbouring possession that contains a replay event; V2 would trigger it too. The adapter's `V3Possession` adds the same team-less-event guard the original already applies to the current possession. Tests show it returns the original's identical list on all 2,441 synthetic and paired-game possessions where the original returns. The only 2025-26 game that reached the crash, `0022500861`, is now a declared alternation rejection: a held-ball turnover.
   - *Alternation failures: decided October 6, 2026.* Keep rejecting them, as the original does: it fails the check on 55 V2 games, including held-ball turnovers at a later clock. The 2025-26 corpus has 53. Individual games can be accepted later only through reviewed entries in the original's bad-possession override file, which the adapter accepts when tied to the exact play-by-play bytes; this needs no code.
2. **Facts V3 lacks.**
   - *Fouled player:* V2 has it for 45,826 of 46,916 fouls. It feeds fouls-drawn statistics, starter inference and a rare and-one branch.
   - *Team-won jump balls:* 100 events in 2024-25. They block 97 games in 2025-26 and 71 in the comparison.
   - Both need evidence beyond the V3 stats feed, such as live play-by-play, which only 1 of 1,230 captures includes.
3. **Recovery evidence.** Some games need recorded data.nba.com order or boxscore starter responses for the original's fallbacks. The comparison has 83 order and 16 starter cases with V2's order; the 2025-26 corpus has 3 order cases.
4. **Integration.**
   - Confirm the parity workflow passes remotely with the line-ending fix.
   - Integrate with `Client` and the data-loader factory. Web and file loading and box-score context building now exist in `stats_nba_v3.web`.
   - Support G League; it needs its own paired evidence, starting with its one-shot free-throw subtypes. WNBA is supported.
   - Settle the detailed-statistics capability gate.
   - Migrate Cheeseburger with versioned imports.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity
.\.venv\Scripts\python.exe -B -m tools.parity.baseline_tests --candidate .
.\.venv\Scripts\python.exe -B -m tools.parity.paired_season
.\.venv\Scripts\python.exe -B -m tools.parity.season_differential
.\.venv\Scripts\python.exe -B -m tools.parity.corpus --output .parity/candidate-v3-corpus.json
```

The corpus audit reads the Cheeseburger ingestion captures listed in the frozen inventory and writes only its report. The latest report is `.parity/candidate-v3-corpus-review-20261006.json`, SHA-256 `039b248d9b537cfb6ae1bc505a539df7c50b49f18a8edc943028636cb5f03669`, after the code-review fixes. Every game's outcome, credits, possessions and reconciliation equal those of the guard run. `.parity/candidate-v3-corpus-final-20261005.json` differs only in game `0022500861`, which moved from a crash to an alternation rejection. That report's comparison with the October 5 baseline is `.parity/corpus-final-changes-20261005.json`.

Earlier checkpoints: [numeric vocabulary](v3-numeric-vocabulary-progress.md), [participants and free throws](v3-participant-and-ft-progress.md), [starter recovery](v3-starter-recovery-progress.md), [exceptions](v3-exception-parity-progress.md), [shot vocabulary](v3-shot-vocabulary-progress.md) and [the initial corpus audit](v3-corpus-audit.md).
