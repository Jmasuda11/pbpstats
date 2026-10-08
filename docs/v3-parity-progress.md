# V3 parity progress — October 6, 2026

## Where things stand

The adapter decodes V3 rows into the original Stats event classes; the original engine makes every enhancement, possession and attribution decision. Paired 2024-25 V2/V3 season exports now give direct evidence for decoding and a full-game comparison against the original on real games. The October 3 checkpoint is preserved in the linked continuation documents.

All results were executed locally. The branch is pushed to `origin/feat/v3-parity`. The parity workflow's first remote run, on `6ca73ed`, failed at its reference check, because the pinned hashes had been computed from Windows (CRLF) checkouts. They now pin committed bytes, and the parity workflow has passed remotely since `20f280a`. The upstream `CI` workflow runs a bare `python -m pytest` through tox on Python 3.8–3.11, which collects the whole suite. It failed on every push on the upstream suite's two known fixture failures, which fail on the original too. The root `conftest.py` now marks exactly those two as strict expected failures, so that workflow passes but still fails if either changes. Both workflows pass remotely on Python 3.8–3.12 since `c4331cc`.

| Check | Result | Scope |
| --- | --- | --- |
| Untouched original suite against the candidate | 116 pass; the same two known fixture failures | Only the earlier starter I/O split changes an original file |
| Parity tests | 899 pass | Harness, adapter, vocabulary, exceptions, corpus, paired seasons, season differential, WNBA, the fetch tool, the held-ball extension and live jump-ball evidence |
| Paired 2024-25 exports | 574,358 of 574,358 events pair one-to-one; period, actor and team agree on every event | [Paired season evidence](v3-paired-season-evidence.md) |
| Decoder against recorded V2 codes | 188 of 188 labels | Was 156 matching, 8 different and 24 rejected; every table entry is checked |
| Full games, equivalent facts | **937 of 937 comparable games identical**; **981 of 981** when the original also has the held-ball extension; **1,098 of 1,098** with live jump-ball evidence too | Floored clocks plus V2 within-instant order; fouled player excluded as a declared gap |
| Full games, V3 order and floored clocks | 565 identical; credited counts equal in all 937 | 69 possessions in 61 games credit a different lineup |
| Full games, exact V3 | Decisions differ in 746 games; +414 credited possessions (+0.22%) | Tenth-of-a-second clocks in final seconds |
| 2025-26 corpus audit | 1,093 research passes; 137 blocked; no crashes | 1,086 before held-ball version 2, 1,047 before the held-ball extension; 521 on October 5, and 189 in the October 3 document |
| Live jump-ball facts against V2 | **2,982 of 2,982 paired jump balls agree**: 2,193 NBA 2024-25, 789 WNBA 2025 | Both jumpers, and the recipient or team; `tools/parity/live_jump_balls.py` |
| WNBA 2025 paired season | 154 of 154 labels decode to the recorded code; with equivalent facts **257 of 257 comparable games identical** with live jump-ball evidence and the held-ball extension on both sides | 203 of 203 without the live evidence; 166 of 167 against the original alone: [WNBA support](v3-wnba-2025.md); three WNBA-only codes |

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
  - `web.save_game()` handles one game, and the command and Cheeseburger's batch script both call it.
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
- **Held-ball turnovers:** the original keeps the possession through a jump ball when the next event is a turnover at the same clock. When the league records that turnover later, as the jump ball is secured, the original instead changes possession at the jump ball and fails its alternation check. The `held_ball_turnover_v2` extension applies the original's same-clock rule at the recorded turnover. It applies where the original would change possession at the jump ball and the first event after it is a turnover by the team that lost the tip. Substitutions logged at the jump ball's clock, made while play was stopped, are passed over, as in `0022500088` Q2 2:38–2:34. It also applies to a held ball on a player who has just made a steal, as video review of `0022500879` Q3 11:23–11:22 confirmed: the steal already changed possession, and the turnover after the tip decides the jump ball's offense. Version 1 covered only a later-clock turnover right after the jump ball. In the 2025-26 corpus audit, version 1 moved 39 blocked games to passing, version 2 seven more, and no other outcome changes. `season_differential --held-ball` installs the same module into the original on V2.
- **Live jump-ball evidence:** `V3JumpBallEvidence` supplies a recorded live play-by-play response, bound to the V3 bytes, for a team-won jump ball's blank description and for a "Tip to" surname two players share. Without it, such a jump ball raises `V3JumpBallEvidenceRequired` with the original's own live URL, keeping its rejection message. The fetch tool requests that URL, records the response and parses again. `tools/parity/live_jump_balls.py` checks every paired V2 jump ball against its live action, independently of the adapter: 2,193 of 2,193 in NBA 2024-25 and 789 of 789 in WNBA 2025 agree. `season_differential --live DIR` gives the adapter those recorded responses.
- **CI line endings:** the reference and prior checks now pin each Git tree and the committed bytes of each file. 197 reference and 231 prior file hashes, and one shot-vocabulary source hash, were re-pinned from CRLF to committed bytes. Each old hash was checked against the CRLF extraction that produced it.

## Remaining work

1. **Policy decisions.**
   - *Clock policy: decided October 5, 2026.* The adapter keeps exact V3 clocks. The whole-second floor projection remains only a comparison diagnostic. Measured cost: decisions differ from V2 in 746 of 937 games, and V3 credits 414 more possessions (+0.22%).
   - *Order policy: decided October 6, 2026.* The adapter keeps V3's recorded same-instant order and the original crediting rule, unchanged. Differences from V2's order are treated as V2 recording quality. [The 69 lineup-credit differences](v3-season-differential.md#why-69-possessions-credit-a-different-lineup) are all zero-second substitutions listed on the other side of the possession's crediting event. In 58 of them V3's placement is the plausible one; in 4, V2's was.
   - *Original crash: decided and implemented October 6, 2026.* The original's `Possession.get_team_ids` raises `AttributeError` when it scans a neighbouring possession that contains a replay event; V2 would trigger it too. The adapter's `V3Possession` adds the same team-less-event guard the original already applies to the current possession. Tests show it returns the original's identical list on all 2,441 synthetic and paired-game possessions where the original returns. The only 2025-26 game that reached the crash, `0022500861`, then became an alternation rejection on a held-ball turnover; it now parses with the held-ball extension.
   - *Alternation failures: decided October 6, 2026; revised the same day for held-ball turnovers.* Keep rejecting them, as the original does, except held-ball turnovers recorded after their jump ball. After video review of `0022500165`, those use the versioned held-ball extension described in [the contract](v3-parity-contract.md); version 2, decided October 7, also passes over substitutions logged between the jump ball and its turnover and covers a held ball on a player who has just made a steal. The 2025-26 corpus had 53 alternation rejections; 7 remain. Individual games can still be accepted only through reviewed corrections tied to the exact play-by-play bytes: entries in the original's override files, or edits of a recorded event's order, subtype or tenths, the original's remedy of editing the play-by-play file. Video review on October 7 led to eight, listed in the [README](../README-PARITY.md); with them and held-ball version 2, every 2025-26 alternation rejection parses. Video review of the five games rejected for other reasons led to five more on October 8: three event-order edits, and two needing new kinds of edit, one for a blocked team heave logged without its side or the block and one for a lodged ball's team rebound logged twice with its jump ball renumbered. Cheeseburger's recorded inputs then parse for all 1,230 regular-season games.
2. **Facts V3 lacks.**
   - *Fouled player:* V2 has it for 45,826 of 46,916 fouls. It feeds fouls-drawn statistics, starter inference and a rare and-one branch.
   - *Team-won jump balls and shared tip surnames: resolved October 7, 2026 with recorded live play-by-play.* V3 leaves 100 team-won jump balls blank in 2024-25; they blocked 97 games in 2025-26 and 71 in the comparison. The live feed records both jumpers and the recipient or team under the same action numbers, and agrees with V2 on all 2,982 paired jump balls. The adapter reads it only for jump balls V3 leaves undecided; see the contract.
   - *Jump-ball side:* a V3 jump-ball row's `teamId`/`location` is its first-named jumper's, always the home team's: all 2,193 paired 2024-25 rows and all 789 WNBA 2025 rows are located `h`. The home team got the ball in 1,036 of 2,093 tips to a player (364 of 734 in WNBA 2025), so the side cannot identify a recipient or a winner.
   - The fouled player still needs evidence beyond the V3 stats feed.
3. **Recovery evidence.** Some games need recorded data.nba.com order or boxscore starter responses for the original's fallbacks. The comparison has 83 order and 16 starter cases with V2's order; the 2025-26 corpus has 3 order cases.
4. **Integration.**
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

The corpus audit reads the Cheeseburger ingestion captures listed in the frozen inventory and writes only its report. The latest report is `.parity/candidate-v3-corpus-corrections-20261008.json`, SHA-256 `77b480c9a1c1fa7b0f575280f7725c461f8c2055cad6f75ccb14f14c34516543`, on the current code. It differs from the previous report, `.parity/candidate-v3-corpus-corrections-20261007c.json`, SHA-256 `94d9ac7c75517ffef83a6d3d39ed816afc1d8ace30e46c0dc9d4070474c2ebc5`, only in implementation hashes. The corpus applies no reviewed corrections, so its outcomes equal those of the held-ball version 2 report, `.parity/candidate-v3-corpus-held-ball-v2-20261007.json`, SHA-256 `eff8bfb01bd59bc094de895c86786991e6d5688a987ba22318bcf595bfc0e62d`. Version 2 moves seven games from blocked to passing: `0022500088`, `0022500479`, `0022500765`, `0022500868`, `0022500994` and `0022501168`, with a substitution logged before the turnover, and `0022500879`, with a held ball after a steal. The other two steal cases, `0022500275` and `0022500506`, stop earlier at team-won jump balls, since the corpus has no live play-by-play. In the other 39 games that use the extension only its version label changes, plus the new diagnostic fields. The previous report, `.parity/candidate-v3-corpus-live-evidence-20261007.json`, SHA-256 `95b7d223d6dd49a2d079522b5cf8cd7220331a1938ef945bb482731fff5ec66d`, was on the code with live jump-ball support; the corpus supplies no live play-by-play. Every outcome equals the held-ball report's; in 97 blocked games the first blocker is now the `V3JumpBallEvidenceRequired` subclass, with the same message. The held-ball report, `.parity/candidate-v3-corpus-held-ball-20261006.json`, SHA-256 `da940a4908b5f8e76e9edb03fd7c4c6d34322e9ae7f0fc40fbf44dbabf916feb`, moved 39 games from blocked to passing. Two blocked games keep their category with a different first message, and the other 1,189 are unchanged (`.parity/corpus-held-ball-changes-20261006.json`). The previous report, `.parity/candidate-v3-corpus-review-20261006.json`, SHA-256 `039b248d9b537cfb6ae1bc505a539df7c50b49f18a8edc943028636cb5f03669`, followed the code-review fixes; every game's outcome, credits, possessions and reconciliation equal those of the guard run. `.parity/candidate-v3-corpus-final-20261005.json` differs only in game `0022500861`, which moved from a crash to an alternation rejection. That report's comparison with the October 5 baseline is `.parity/corpus-final-changes-20261005.json`.

Earlier checkpoints: [numeric vocabulary](v3-numeric-vocabulary-progress.md), [participants and free throws](v3-participant-and-ft-progress.md), [starter recovery](v3-starter-recovery-progress.md), [exceptions](v3-exception-parity-progress.md), [shot vocabulary](v3-shot-vocabulary-progress.md) and [the initial corpus audit](v3-corpus-audit.md).
