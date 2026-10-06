# Recorded numeric vocabulary audit — October 3, 2026

The first vocabulary continuation adds ten shot subtypes, corrects Clear Path and numbered technical FT codes, and adds three-attempt flagrant FTs. Every one of the 48 ordinary shot labels and 17 FT labels observed in the bundled season recordings now has an independently pinned numeric-code observation. The candidate still uses the original event classes and basketball methods.

This completes the observed shot/FT vocabulary slice, not all of point 1 or full parity. Other event families, team-only heaves, historical code aliases and detailed statistical completeness remain open.

## Recorded evidence

`tests/parity/shot-vocabulary.json` now contains 48 mappings; `tests/parity/free-throw-vocabulary.json` contains 17. Each mapping records an exact V2 observation, a native V3 observation, source indices and byte hashes. These are cross-recording vocabulary observations, not paired-game equality claims.

The new V2 evidence is the complete `nbastats_2024.tar.xz` archive from [shufinskiy/nba_data at revision e829d4678be1e075f99e5d41a1c5f97089be446b](https://github.com/shufinskiy/nba_data/tree/e829d4678be1e075f99e5d41a1c5f97089be446b), retained unchanged under `tests/parity/data/nba_data/` with the collector, builder, README and license. Archive SHA-256: `8f370da00ad0a6d4157921bd161d56ea32647a165d906516f2b36384a6a4989a`.

This is a community CSV export of PlayByPlayV2, **not raw HTTP JSON, an NBA-hosted archive, or a replacement behavioral oracle**. The pinned collector explicitly requests PlayByPlayV2; the builder concatenates the exported tables. Observation dictionaries preserve CSV text values, including unpadded game IDs and empty cells. Tests verify the archive, decompressed member, provenance files and exact cited rows offline. The archive is read in memory without filesystem extraction. Seven additional native V3 files were copied byte-for-byte from existing hash-verified ingestion captures; source captures remain unchanged.

The pinned original `e7ccf2fb6326da630a3cf1665aac964a1e108f4c` remains the behavioral oracle. The previous parser contributes only recorded V3 input files.

## Implemented mappings

| Added shot subtype | Recorded code | Previous first-blocked games |
| --- | ---: | ---: |
| Cutting Finger Roll Layup Shot | 99 | 187 |
| Running Reverse Layup Shot | 74 | 161 |
| Driving Bank Hook Shot | 93 | 117 |
| Turnaround Bank shot | 85 | 85 |
| Fadeaway Bank shot | 83 | 33 |
| Hook Bank Shot | 67 | 22 |
| Reverse Dunk Shot | 51 | 21 |
| Step Back Bank Jump Shot | 104 | 16 |
| Driving Reverse Dunk Shot | 109 | 8 |
| Running Reverse Dunk Shot | 110 | 7 |

All 38 previously supported shot labels were also audited against recorded evidence. The complete-input shot suite now compares 48 mappings × made, assisted, missed and blocked outcomes: **192/192 snapshots and credit summaries match**. It checks action codes, coordinates, distance/type, shot data, assist/block identities, direct original-event statistics, lineups and possession observations. Deliberate code/location/identity drift remains detectable, and unreviewed strings still reject.

| FT family | Previously decoded codes | Recorded codes now used |
| --- | --- | --- |
| Clear Path 1/2, 2/2 | 17, 18 | 25, 26 |
| Flagrant 1/3, 2/3, 3/3 | Rejected | 27, 28, 29 |
| Technical 1/2, 2/2 | 16, 16 | 21, 22 |
| Unnumbered technical | 16 | 16, independently verified |
| Ordinary 1-, 2-, 3-attempt FTs | 10–15 | Unchanged, independently verified |
| Flagrant 1/1 and 1/2, 2/2 | 20 and 18, 19 | Unchanged, independently verified |

The expanded FT suite compares every make/miss combination with and without a substitution before the final attempt: **76/76 snapshots and credits match**. It checks exact action codes, FT predicates, foul association, efficiency-lineup attribution and direct statistics. The original quirks remain: Clear Path 25/26 are not first/end FT predicates; flagrant 27 is a first attempt but 28/29 are not ordinary second/last predicates; flagrant 1/1 keeps the original “1 Shot Away From Play” label. Technical FTs have no ordinary foul association but still credit the original efficiency lineup. Unsupported technical numbering now rejects instead of silently becoming code 16.

The frozen `scenarios.py` encoder remains unchanged. Its inherited Clear Path and flagrant encodings are not factual evidence; their matching old snapshots were insufficient to detect these numeric mistakes.

## Historical aliases remain a parity limit

Five labels have multiple recorded V2 codes:

| V3 label | Retained constructor code | Also recorded |
| --- | ---: | ---: |
| Driving Dunk Shot | 49 | 9 |
| Driving Layup Shot | 6 | 42 |
| Running Jump Shot | 2 | 46 |
| Hook Shot | 3 | 55 |
| Jump Shot | 1 | 45 |

Exact observations are retained under `unresolved_aliases`, with regression checks. V3 subtype text alone cannot recover which historical numeric identity an equivalent V2 row used. The existing constructor choices are retained; exact action-code equality across those recordings is **not established**. A compatibility policy and explicit behavioral comparisons of aliases are still needed. A passing selected-code fixture does not resolve this ambiguity.

## Complete season rerun

| Outcome / first blocker | Starter checkpoint | Vocabulary checkpoint |
| --- | ---: | ---: |
| Research checks passed | 40 | 189 |
| Unsupported ordinary shot subtype | 657 | 0 |
| Other adapter blockers | 495 | 993 |
| Preparation blockers | 35 | 35 |
| Invalid official-minute strings | 3 | 13 |
| Unexpected errors | 0 | 0 |
| Total games | 1,230 | 1,230 |
| Adapter completed (includes minute blockers) | 43 | 202 |
| Publication accepted | 0 | 0 |

Exactly **671 first outcomes change and 559 remain identical**, also true of the complete per-game records. The changed game-ID set is exactly the previously blocked 657 shot cases plus 14 three-attempt flagrant cases. All 40 earlier passes remain; 149 additional games pass research checks. Source hashes, capture identities and historical statuses match across audits. The corrected Clear Path/technical codes are independently verified even where their previously observed gate outcomes do not change.

All 1,230 games remain represented; 1,195 contexts are prepared. The new report has 1,041 blocked games: 993 adapter blockers, 35 preparation blockers and 13 minute-format blockers. These are first blockers, so clearing one can expose another. Full source-order and alternating-possession checks stay enabled. All games retain `full_game_validated=False`; aggregate detailed statistics remain unavailable.

The largest remaining first blockers are team-only heaves (552), replay-center events (87), missing explicit jump-ball roles (56), actors absent from recorded rosters (54), double-dribble turnovers (42), ambiguous participants (33), five-second turnovers (32) and altercation rulings (30). There are now eight original alternation failures: `0022500088`, `0022500319`, `0022500462`, `0022500466`, `0022500479`, `0022500660`, `0022500679`, `0022501229`. The original two remain; six became reachable after decoding earlier shots. No validation was bypassed.

The thirteen minute-format failures are `0022500133`, `0022500140`, `0022500195`, `0022500202`, `0022500254`, `0022500361`, `0022500371`, `0022500391`, `0022500627`, `0022500658`, `0022500819`, `0022501176`, `0022501192`. All retain recorded `:60` seconds and fail format validation; they are not demonstrated numerical minute disagreements. The FT/foul-association review for `0022501050` remains open.

## Verification and reproduction

- New harness/adapter tests: **590 passed**.
- Shot suite: **192/192** matching snapshots and credits.
- FT suite: **76/76** matching snapshots and credits.
- Exception suite: **70/70** matching declared observations, comprising 40 returns and 30 expected exceptions.
- Untouched original tests, and original tests against candidate: **116 passed plus the same two exact known fixture failures** in each run.
- 182/183 original production Python files remain unchanged; only the earlier shared starter I/O extraction differs. This continuation changes the V3 adapter and parity tooling, without changing the pinned reference, source captures, imports or parser selection.
- Differential reports now include harness and vocabulary-evidence hashes in addition to package/input hashes. All executed report fingerprints were checked against the final implementation. CI remains authored but has not run remotely.

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --suite shots --output .parity/candidate-v3-shots-vocabulary.json
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --suite free-throws --output .parity/candidate-v3-free-throws-vocabulary.json
.\.venv\Scripts\python.exe -B -m tools.parity.exceptions --output .parity/exception-parity-vocabulary.json
.\.venv\Scripts\python.exe -B -m tools.parity.corpus --output .parity/candidate-v3-corpus-vocabulary.json
.\.venv\Scripts\python.exe -B -m tools.parity.corpus_diff --before .parity/candidate-v3-corpus-starters.json --after .parity/candidate-v3-corpus-vocabulary.json --output .parity/corpus-vocabulary-changes.json
```

Executed report SHA-256 values:

| Report | SHA-256 |
| --- | --- |
| Corpus | `741de987f779517c8d72fc367b9d2aed06ade06eb4df12562e10cc86231af7a5` |
| Corpus outcome comparison | `d793114e7f9c0f0d50f134754e4dd588b83da23d7832b97514ca088ee9b8a57f` |
| Shots | `cbb74b75b71d72c09476e7bc656dde981951227a9223373283c97c3cbc36ca70` |
| FTs | `9dbe7f6c96f16918b4059607e149171bfba5f5f52eb3eb8c37318da455b85930` |
| Exceptions | `40d410a2dd0f447e03841403e787cd347d82275785e680392a414e03a049d5c6` |

## Remaining work within point 1

1. Audit and extend non-shot vocabulary: replay/ejection records, turnover variants and remaining foul subtypes. Use recorded code/role evidence and differential snapshots.
2. Specify team-only heaves as an explicit extension, preserving team attribution and defining their statistical/possession effects; do not convert them to ordinary player shots.
3. Resolve the historical shot-code alias contract and compare original behavior under each recorded code before claiming exact numeric identity parity.
4. Continue the complete corpus comparisons with unchanged source evidence and validation gates. Participant, exception, detailed-statistics, league and ingestion work remains in the broader plan.
