# Fresh V3 compatibility work

Start here for the new implementation. The original upstream README and pinned oracle remain unchanged. One candidate production file now separates starter request/response I/O into shared methods, verified against the pinned original; the other 182 original Python files are unchanged.

- Branch: `feat/v3-parity`.
- Upstream starting point: `e7ccf2fb6326da630a3cf1665aac964a1e108f4c`.
- Origin: `https://github.com/Jmasuda11/pbpstats.git`; upstream: `https://github.com/dblackrun/pbpstats.git`.
- This independent clone was created from the existing local Git history with `--no-hardlinks`, then checked out at the original upstream revision. No previous working-tree files were copied into the implementation.
- This checkout has its own `.venv`; the existing parser and Cheeseburger environment have not been switched.

Read [the approved phased plan](docs/v3-parity-plan.md), [the compatibility contract](docs/v3-parity-contract.md), and [current progress](docs/v3-parity-progress.md).

## Run the checks

From this checkout on Windows:

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.baseline_tests
.\.venv\Scripts\python.exe -B -m tools.parity.baseline_tests --candidate .
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --output .parity/candidate-v3-synthetic.json
.\.venv\Scripts\python.exe -B -m tools.parity.known_differences
.\.venv\Scripts\python.exe -B -m tools.parity.exceptions
.\.venv\Scripts\python.exe -B -m tools.parity.paired_season
.\.venv\Scripts\python.exe -B -m tools.parity.season_differential
```

The last two commands use the pinned paired 2024-25 V2/V3 exports. `season_differential` runs every game through the original engine on V2 and the adapter on V3, in isolated offline workers; it takes about 30 minutes and writes `.parity/season-differential-2024.json`. Use `--limit N` or `--game ID` for a quick run.

For a new environment, use Python 3.12 and `python -m pip install -r tools/parity/requirements-py312.txt`. The dependency lock describes the tested Python 3.12 environment, not the entire legacy Python support matrix. No editable install of the old checkout is required. The workers run with isolated imports and verify the actual loaded package path.

The reference runner reconstructs frozen source from Git and verifies the pinned tree and source/fixture hashes in `tests/parity/manifest.json`. The hashes are of committed bytes, so they hold whatever the local line-ending settings. A clone that does not contain the previous attempt also needs its pinned commit:

```powershell
git fetch --no-tags https://github.com/Jmasuda11/pbpstats.git 95e4dd5bda36c8d87d0c443a0298628cacccfa02
```

Paired-game differences are expected and reported explicitly:

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.run --provider v3 --suite paired --expect-differences --output .parity/candidate-v3-paired.json
```

`--expect-differences` is an audit mode, never the release gate. The paired-game tests separately assert the known clock effects, event correspondence and ordering difference. Reports live in ignored `.parity/`; source hashes and fixture provenance remain tracked.

Audit every game in the frozen season inventory with independently reconstructed recorded context:

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.corpus
```

See [the initial corpus audit](docs/v3-corpus-audit.md) for the 1,230-game results and evidence limits. The command writes `.parity/candidate-v3-corpus.json`, preserves every blocked game and runs offline in an isolated process. `--require-all` returns a failure for any research blocker; unexpected errors always fail. Passing these checks does not enable publication or detailed statistics.

The [latest numeric vocabulary continuation](docs/v3-numeric-vocabulary-progress.md) adds ten shot mappings, corrects Clear Path/numbered technical FT codes and supports three-attempt flagrant FTs. All 48 observed ordinary shot labels and 17 FT labels have independent recorded evidence; five historical shot-code aliases remain explicit limits. The focused suites pass 192 shot cases, three participant cases and 76 FT cases, with 590 total parity tests. The complete season audit has 189 research passes and 202 adapter completions. Run the suites with `--suite shots`, `--suite participants` and `--suite free-throws`. Compare complete corpus outcomes with `python -m tools.parity.corpus_diff --before BEFORE.json --after AFTER.json`. The [participant checkpoint](docs/v3-participant-and-ft-progress.md) and [earlier shot checkpoint](docs/v3-shot-vocabulary-progress.md) remain available.

The [paired 2024-25 season evidence](docs/v3-paired-season-evidence.md) adds the V3 export for the same games as the pinned V2 export. All 574,358 events pair one-to-one by event number, and each of the 188 V3 labels has exactly one recorded V2 code. The decoder now produces the recorded code for all 188 labels; before this correction it matched 156, differed on 8 and rejected 24. Regenerate the facts and decoder comparison with `python -m tools.parity.paired_season`.

The [season differential](docs/v3-season-differential.md) runs every paired game through the original on V2 and the adapter on V3. With equivalent facts, all 937 games that both complete are identical: credits, possessions, events and statistics. The fouled player is excluded because V3 does not record it. With V3's own facts, same-instant order changes possession membership in 368 games and credited lineups for 69 possessions. Exact V3 clocks change decisions in 746 games and add 414 credited possessions. The 2025-26 corpus audit now has 1,047 research passes.

## Current adapter

`pbpstats.data_loader.stats_nba_v3.StatsNbaV3PossessionLoader` accepts V3 source bytes and a `V3Context` containing source provenance, a matching PBP hash, two NBA teams, a recorded roster with names, and any explicitly supplied period starters. Omitted periods use original event inference and scoped starter overrides, with optional `starter_boxscores={period: V3StarterBoxscore(...)}` for recorded interval responses when recovery is needed. It builds the **original** Stats enhanced-event classes through their factory and reuses original enhancement, order repairs, possession decisions and attribution.

The original loader's repair input is a temporary in-memory constructor projection. Source bytes, raw rows and per-event source indices remain separate. File-writing repair hooks record diagnostics instead. Optional `V3Overrides` supplies recorded legacy bad-possession/boundary correction files; optional `V3EventOrder` supplies a recorded provider response for the original ordering fallback. Both require provenance and the exact PBP hash. Missing provider evidence still blocks recovery without making a network call. Existing V2 loaders are untouched.

The [starter recovery continuation](docs/v3-starter-recovery-progress.md) documents 70 matching declared observations, including 29 new full-loader starter cases, exact exception classes/messages/context, scoped overrides, repairs and selected HTTP/JSON failures. Broader source/API and ingestion behavior remain open gates. The [initial exception checkpoint](docs/v3-exception-parity-progress.md) preserves the earlier 41-case results.

This is an **experimental, bounded NBA adapter**, not the replacement for Cheeseburger's game API. Unknown event vocabulary/participants fail explicitly. Detailed statistics are unavailable at the adapter's aggregate API until attribution completeness is implemented; original event objects are exposed for compatibility research and their direct statistics must not be treated as complete V3 outputs. `full_game_validated` stays false because schedule, official-box validation and the full evidence contract are not implemented here.

Synthetic sequence checks explicitly bypass full source-order and alternating-possession validation, matching the original synthetic worker's scope. The recorded-game checks run both validations. Passing a synthetic case is not a full-game acceptance claim.
