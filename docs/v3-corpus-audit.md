# Initial new-adapter season audit — October 2, 2026

This document preserves the initial baseline. See [the subsequent shot-vocabulary update](v3-shot-vocabulary-progress.md) for the current 11 completed adapter runs and nine research passes. The initial report is retained locally as `.parity/candidate-v3-corpus-initial.json`.

The offline runner accounts for all 1,230 games in the existing 2025–26 inventory. It prepares context for 1,109 games, but **no season game completes the bounded adapter**. These are current research-gate outcomes, not historical V2 comparisons or production acceptance decisions. The previous report's 999 validated / 231 blocked outcomes remain historical evidence.

| First blocking gate | Games |
| --- | ---: |
| Unsupported shot subtype | 995 |
| Other adapter decoding/participant support | 114 |
| Unresolved or ambiguous preparation name | 99 |
| Missing bundled input | 17 |
| Insufficient overtime starter witnesses | 5 |
| Unexpected implementation error | 0 |
| Total | 1,230 |

Of the 1,109 prepared games, 908 were previously validated and 201 were previously blocked. All 999 formerly validated games are blocked by the current research gates, as are all 231 formerly blocked games. No acceptance improvement is claimed. The report retains each game's prior status, current status, first blocker, available raw-row context, source hashes and preparation provenance.

## What preparation establishes

`tools/parity/recorded.py` reads inventoried raw V3 PBP, the full box roster, and its hash-bound provenance assertion. It derives period starters from explicit actors and uniquely resolved participant names witnessed before an entrance, plus exactly-five Q1 box starter markers. The names include ID-bound box/PBP aliases and accent-stripped variants; collisions are rejected. Unknown names are never guessed from roster order.

The derivation uses no prior parser imports, inferred participants, readiness flags, context fingerprints or snapshot fingerprints. Where saved lineup evidence exists, its starter assertions must agree with the independently derived sets. This comparison succeeds for 231 prepared games. Source hashes bind the new evidence to the exact captured bytes, including supplementary files that are not interpreted by this initial preparer.

Preparation checks contiguous periods, one opening/closing marker per period, regulation/overtime marker clocks, and exact nonincreasing raw clocks. It remains conditional on the recorded substitution stream: provider completeness assertions and on-court witnesses do not establish that every real substitution was captured. A subsequent check independently accumulates each player's time from raw substitutions, compares adapter time within 0.000001 seconds and official box minutes within one second, and reconciles the final score and raw-row/substitution coverage. Those checks pass independent test recordings; no season game reaches them yet. `full_game_validated` remains false.

The seventeen missing-input games contain only `pbp.json` and `boxscore.json` in the frozen source manifest; they need separately reviewed bundle preparation. The five insufficient starter cases are `0022500001`, `0022500458`, `0022500521`, `0022500637` and `0022500955`, each missing an independently established fifth starter in overtime. Saved/manual assertions alone are not substituted for that evidence. In particular, the separate live OT evidence for `0022500001` needs its own verification path.

## Next evidence-backed extensions

The largest shot-subtype first blockers are Running Dunk Shot (233), Driving Dunk Shot (192), Reverse Layup Shot (89), Dunk Shot (78), Alley Oop Layup shot (62), Running Alley Oop Dunk Shot (62), Cutting Finger Roll Layup Shot (60) and Running Reverse Layup Shot (57). No new action code or generic fallback was added during this audit. Pin the relevant original source observations and add differential cases before expanding the mapping.

Preparation name blockers include Hansen (42), Jal. Williams (18), St. Curry (5), Green (5), Jones (4) and Williams (4). Some require additional ID-bound aliases; others are ambiguous across rosters. More permissive matching would conceal these distinctions. Other adapter blockers include team-only heaves, replay vocabulary, team-only jump recovery, unrecorded actors and unsupported turnover/free-throw patterns. Counts describe the first failed gate only; resolving one blocker may expose another in the same game.

## Reproduce and inspect

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.corpus
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity
```

The corpus command launches an isolated subprocess, verifies the loaded package path, blocks network connections and writes `.parity/candidate-v3-corpus.json`. The report includes the inventory hash, prior-report hash and current parser/tool source hashes. The runner refuses an output inside the ingestion root, and verifies that the inventory has not removed a game, changed a capture or omitted a previously hashed file. It performs no source repairs on disk and makes no database connections. Use `--require-all` to return a nonzero exit status for research blockers; unexpected errors always return nonzero. The standard mode permits blockers so the full report remains inspectable.

Executed report SHA-256: `e1701d0b4219921cd1410448bedb1bfd19f2459dfac7b427b7589230361075ea`. Inventory SHA-256: `bcea844a4f77714dc6bc73da0ca8b1bc6d08325f6c4a3d817ca71a520b0cb1dc`. A post-audit inventory is byte-identical to the original, and all implementation hashes in the report match the current source files.

Validation: 53 parity/harness/corpus checks pass (36 existing plus 17 new). The untouched upstream suite remains 116 passing with its two exact known free-throw fixture failures. All source recordings remain unchanged. Remote CI has not been run.
