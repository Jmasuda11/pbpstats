# Participant evidence, shot coverage and a free-throw correction — October 2, 2026

Full parity remains the goal. This continuation raises prepared season context from 1,109 to 1,195 games and research passes from nine to 40. It also fixes a real statistical decoding error that the inherited 145-case snapshot comparison did not detect. All 1,230 games remain accounted for; detailed aggregate statistics and publication remain gated.

## Participant evidence

`recorded-context-v3` adds aliases from bounded descriptions whose actor is explicitly identified by the row's `personId`: outgoing substitutions, rebounds, secondary steals/blocks and free throws. Incoming substitutes, assisters, opposing jumpers and tip recipients cannot supply aliases for the row's actor. New aliases retain the exact source index, action number, player, team and role. Contradictory identities reject; existing collisions are retained.

This resolves 63 preparation blockers. There are 64 changed first outcomes because one game advances to a later unresolved name without completing preparation. Game `0022500349` becomes a research pass.

Ambiguous jump-ball recipients may be narrowed by independently reconstructed five-player lineups. Preparation defers ambiguous tips until starters have been established without those tips. The adapter separately tracks the supplied starters and explicit substitutions, requires exactly one matching player on court, then rechecks that lineup against the original enhanced events after source-order repair. It records all name candidates and the lineup used. A tip cannot supply the starter evidence used to disambiguate itself.

This prepares another 23 games. The stage has 31 changed first outcomes: 23 advance to adapter checks, one exposes insufficient overtime starters, and seven remain ambiguous with richer diagnostics. Three complete-input cases match the isolated original V2 engine, including participant fields, lineups, possession credits and direct shot statistics. Tests also reject two or zero matching players on court, invalid substitutions, stale period lineups and disagreement with original enhanced lineups.

An experiment treating every official given name as a display alias was removed: it introduced ambiguity between actual display names and other players' given names, including Mitchell/Mitchell Robinson and Jordan/DeAndre Jordan. Its audit remains as `.parity/candidate-v3-corpus-context-v4.json` for investigation, but it is **not** the current implementation or default report. Five Hansen cases still require an explicit alias witness or independently verified cross-recording evidence.

## Additional shot evidence

Three additional mappings are pinned in `tests/parity/shot-vocabulary.json`:

| V3 subtype | V2 code | Recorded V2 event in 0021800621 |
| --- | ---: | ---: |
| Alley Oop Layup shot | 43 | 221 |
| Putback Dunk Shot | 87 | 36 |
| Running Alley Oop Dunk Shot | 106 | 658 |

The V2 source is the [community-published response recording](https://gist.github.com/basketballrelativity/492677e5cec38ae0bab8fa29bc0366f0), not an NBA-hosted capture or an original upstream fixture. Its Gist revision is `619ccc7859387d06c153ae84470aa97ce06c4150`, published March 16, 2020. The downloaded bytes are retained in `tests/parity/data/pbpv2_0021800621.json`, with SHA-256 `f8984c0c89695233691e4e2a1a011684ec98a4facf8488cf2e60fea1a6fe3edf`. The manifest records the exact raw URL, hash, rows and source indices. Tests verify these bytes offline and compare their labels with pinned native V3 recordings from the prior archive; no prior-parser decisions supply expected results.

The shot suite now has 32 cases: eight additional recorded mappings, each tested as made, assisted, missed and blocked. All match original V2 action codes, selected enhanced observations, direct shot statistics and possession credits with complete coordinates. This stage changes 384 first outcomes and adds 29 research passes. The original five-mapping milestone is retained in [its historical report](v3-shot-vocabulary-progress.md).

## Statistical bug exposed by independent evidence

Events 485 and 486 in the new V2 recording encode flagrant free throws 1-of-2 and 2-of-2 as **18 and 19**. Both the initial adapter and the frozen synthetic encoder used 19 and 20. Code 20 is explicitly flagrant 1-of-1 in the original `StatsFreeThrow.is_ft_1_of_1` implementation.

The adapter now uses 18/19 for the two-attempt trip and supports 20 for one-attempt flagrant trips. The old second-attempt code falsely set `is_first_ft` and emitted an extra free-throw-trip statistic. The inherited snapshots omitted those observations, so their 145/145 equality still passes after this correction. That result is useful only within its stated property inventory; it was never proof of complete decoding or statistics.

A separate `free-throws` suite independently supplies the corrected V2 codes. Twelve cases cover every make/miss combination for one- and two-attempt trips, with and without substitutions. Snapshots include exact action codes, FT predicates, foul/efficiency associations, direct FT statistics and lineup attribution. They require evaluated values rather than unavailable placeholders. A regression deliberately restores code 20 for the second attempt and verifies the resulting extra trip statistic is detected.

Original quirks remain observable: flagrant 18/19 attempts do not set the original first/end-FT predicates, and the original engine labels the isolated one-attempt case `1 Shot Away From Play`. Made-FT efficiency credit remains with the foul-time lineup after a substitution. Foul-drawn attribution is still unavailable; these focused FT checks do not enable aggregate detailed statistics. Three-attempt flagrant mappings remain blocked pending evidence. Clear Path and other inherited numeric mappings still need independent source assertions.

The corpus first-outcome comparison changes six games at this stage, all previously blocked on flagrant 1-of-1. One, `0022501098`, becomes a research pass. Correcting two-attempt FT statistics is covered by the detailed differential suite, not by the corpus outcome comparator, which does not compare every event statistic.

## Final season audit

| Outcome / first blocker | Before this continuation | Current |
| --- | ---: | ---: |
| Context prepared | 1,109 | 1,195 |
| Adapter completed | 11 | 43 |
| Research checks passed | 9 | 40 |
| Unsupported shot subtype | 789 | 657 |
| Other adapter blockers | 309 | 495 |
| Preparation blockers | 121 | 35 |
| Reconciliation blockers | 2 | 3 |
| Crashes | 0 | 0 |
| Publication accepted | 0 | 0 |

Compared with `.parity/candidate-v3-corpus-shots.json`, 447 first outcomes changed and 783 did not. There are 31 new research passes and no lost passes. The per-game ledger verifies identical source hashes, captures and historical statuses for every game. Stage comparisons are retained as `corpus-name-changes.json`, `corpus-lineup-name-changes.json`, `corpus-expanded-shot-changes.json` and `corpus-flagrant-changes.json`. Stage counts overlap; they must not be summed as unique games.

The remaining preparation blockers are 12 participant ambiguities/unresolved names, six insufficient overtime starter sets and 17 captures without the required bundled inputs/provenance. The additional overtime case is `0022501029`; its formerly ambiguous tip could not be used to invent a fifth starter. The seven genuinely ambiguous tip cases retain multiple matching players on court. Five unresolved Hansen aliases remain.

The largest adapter blockers are team-only heaves (255), cutting finger-roll layups (187), running reverse layups (161), driving bank hooks (117) and turnaround bank shots (85). Two games now reach the original alternation check and reject: `0022500088` and `0022500660`. These require source/order investigation, not bypassing the original check.

Three otherwise completed games contain invalid official minute strings: `0022500361` / player 1642366 / `25:60`, `0022500627` / player 1628976 / `19:60`, and `0022500819` / player 1630579 / `23:60`. They remain blocked without normalization. The previously flagged FT-association review for `0022501050` also remains open despite its narrower research pass.

Current audit: `.parity/candidate-v3-corpus-flagrant.json`, also copied byte-for-byte to `.parity/candidate-v3-corpus.json`, SHA-256 `f19786c27b3d5f150f66562bc5fa5a709cb6bae759dfd70b27189c7e79d72b3e`. Full continuation ledger: `.parity/corpus-continuation-changes.json`, SHA-256 `fa3047c4a0ee1584e66090f49f3a05b4d450e6c15d112f0bdbdff9fd3606aa36`. Every implementation hash in the final audit matches the retained implementation after removing the given-name experiment.

## Verification and next gates

The new parity suite passes 170 tests. The untouched original suite remains 116 passed with its two exact documented fixture failures. All 183 original production Python files retain their baseline hashes. The season inventory remains byte-identical at SHA-256 `bcea844a4f77714dc6bc73da0ca8b1bc6d08325f6c4a3d817ca71a520b0cb1dc`. Source captures are unchanged.

Run the additional comparisons:

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --suite shots
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --suite participants
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --suite free-throws
.\.venv\Scripts\python.exe -B -m tools.parity.corpus
```

Next gates remain independent vocabulary verification (including existing mappings), complete attribution and statistics, remaining source/lineup evidence, full-game output comparisons, explicit league extensions, and verified versioned application integration. A published nba_api notebook offers a lead for cutting finger-roll code 99, but its generating cell uses the V1 endpoint; it has not been promoted as a raw V2 recording. No unsupported subtype is assigned a generic code to improve coverage.
