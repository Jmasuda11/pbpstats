# Recorded shot vocabulary and season progress — October 2, 2026

This is the historical five-mapping checkpoint. See [the subsequent participant and FT update](v3-participant-and-ft-progress.md) for the current eight additional shot mappings, 32 shot comparisons, FT correction and 40 season research passes.

Five explicit V3 shot mappings now reuse the original event classes. Twenty complete-input cases match untouched V2 snapshots and possession credits. In the full season audit, 11 games finish the adapter and nine also pass the implemented research checks; all 1,230 games remain in the report.

## Mapping evidence

The tracked `tests/parity/shot-vocabulary.json` records exact raw V2 and V3 rows, source indices, file hashes and pinned revisions. Tests re-read the original archives and verify every observation. These are equivalent shot mechanics observed in separate recordings, not paired historical games or previous-parser decisions.

| V3 subtype | Original V2 code | Pinned V2 recording / event | Pinned V3 recording / action |
| --- | ---: | --- | --- |
| Running Dunk Shot | 50 | `0021600270` / 367 | `stats_v3_0022400001.json` / 574 |
| Driving Dunk Shot | 49 | `0021600270` / 56 | `stats_v3_0022400001.json` / 86 |
| Dunk Shot | 7 | `0021600270` / 23 | `stats_v3_0022400001.json` / 196 |
| Reverse Layup Shot | 44 | `0021600270` / 449 | `0022500165` / 207 |
| Finger Roll Layup Shot | 71 | `2021900002` / 27 | `0022500001` / 371 |

For each subtype, independently encoded made, assisted, missed and blocked sequences run in separate original/candidate processes. Coordinates are present for every shot. The observations include action codes, shot location/type/distance, shot data, assist and block identities, direct original-event statistics, lineups, boundaries and credits. No unavailable-property placeholders are accepted in these cases. Deliberately changing action codes, coordinates, assists or blockers fails the comparison. Unknown related subtype strings still fail decoding.

Direct statistics are inspected only on these complete shot fixtures. This does not establish attribution completeness for full games; aggregate V3 detailed statistics remain unavailable. Historical source bytes and original production Python files are unchanged.

## All-game outcome comparison

| Outcome / first blocker | Initial audit | After five mappings |
| --- | ---: | ---: |
| Research checks passed | 0 | 9 |
| Unsupported shot subtype | 995 | 789 |
| Other adapter blockers | 114 | 309 |
| Preparation blockers | 121 | 121 |
| Official-minute format blockers | 0 | 2 |
| Unexpected errors | 0 | 0 |
| Total | 1,230 | 1,230 |

Exactly 616 first outcomes change and 614 remain identical. The changed game IDs equal the set previously blocked by the five added subtypes. All input hashes and prepared evidence are identical between audits. Each change is recorded in `.parity/corpus-outcome-changes.json`; resolving the earlier shot blocker frequently exposes another unsupported event later in the same game. The comparison refuses missing games, duplicate IDs, changed captures, source hashes or historical status records.

The nine research passes are `0022500106`, `0022500354`, `0022500487`, `0022500516`, `0022500702`, `0022500706`, `0022501037`, `0022501050` and `0022501067`. All reconcile the final score, complete raw-row/substitution coverage, raw-substitution player time against original-adapter time within 0.000001 seconds, and individual official minutes within one second. No source-order repairs were needed for these games.

Eight had historical `validated` status. The ninth, `0022501050`, was previously rejected for an FT trip lacking an unconsumed compatible foul at the exact clock (source row 296). The current path inherits original V2 association behavior and passes its implemented accounting checks; it does not reproduce every previous validation gate. That case still needs a focused association review. All nine retain `full_game_validated=False`, and publication acceptance remains zero.

Two other adapter completions remain blocked: `0022500627` records Wendell Carter Jr. with `19:60` minutes, and `0022500819` records Jericho Sims with `23:60`. These fail the official minute-format check; they are not demonstrated numerical minute disagreements. The diagnostics retain the raw strings, and no normalization is performed. A separately tested interpretation of these recorded durations is required.

The largest remaining shot blockers are Alley Oop Layup shot (145), Running Alley Oop Dunk Shot (127), Cutting Finger Roll Layup Shot (125) and Running Reverse Layup Shot (100). Team-only heaves independently block 145 games. These require new source evidence or explicit extension policies, not generic shot fallbacks.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --suite shots --output .parity/candidate-v3-shots.json
.\.venv\Scripts\python.exe -B -m tools.parity.corpus --output .parity/candidate-v3-corpus-shots.json
.\.venv\Scripts\python.exe -B -m tools.parity.corpus_diff --before .parity/candidate-v3-corpus-initial.json --after .parity/candidate-v3-corpus-shots.json
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity
```

Validation: 97 checks pass, including 20 complete-shot differential cases. The unchanged original suite remains 116 passing plus its two exact known fixture failures. Remote CI has not run. Corpus and differential reports include package/source fingerprints and source hashes; the frozen initial audit remains available for comparison.

Executed corpus SHA-256: `e96af133cf9d603c4015ce55e5f52e3c417aab41c1712958fb2c6824007d5d97`. Outcome comparison SHA-256: `351c9ffb33f4999a0e60b635351dd7e0e8cde34a66bf8c715c03771b4a5871ca`. Complete-shot differential SHA-256: `c36c5459e79b9fc0266c1c983d76da13747de49e03a2586d578479a2b17ff281`. The post-run source inventory is byte-identical to the initial inventory, all original Python hashes still match, and the corpus implementation hashes match the current code.
