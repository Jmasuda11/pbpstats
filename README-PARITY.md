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

GitHub runs two workflows. The parity workflow runs the checks above on Python 3.12. The upstream `CI` workflow runs a bare `python -m pytest` through tox on Python 3.8–3.11. There, the root `conftest.py` marks the upstream suite's two known fixture failures as strict expected failures, while `baseline_tests` still verifies them against the original.

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

The [season differential](docs/v3-season-differential.md) runs every paired game through the original on V2 and the adapter on V3. With equivalent facts, all 937 games that both complete are identical: credits, possessions, events and statistics. With the recorded live play-by-play for undecided jump balls, and the held-ball extension on both sides, all 1,098 are. The fouled player is excluded because V3 does not record it. With V3's own facts, same-instant order changes possession membership in 368 games and credited lineups for 69 possessions. Exact V3 clocks change decisions in 746 games and add 414 credited possessions. The 2025-26 corpus audit now has 1,093 research passes, 46 of them from the held-ball extension.

The [WNBA 2025 paired season](docs/v3-wnba-2025.md) extends the same evidence to the WNBA. All 110,003 events in 286 games pair one-to-one, and the decoder produces the recorded V2 code for all 154 labels, three of them WNBA-only. With equivalent facts, all 167 games that both sides complete are identical. Run it with `--season wnba-2025` on `paired_season` and `season_differential`.

## Fetch a game and save possessions as JSON

From the checkout root:

```powershell
.\.venv\Scripts\python.exe -m pbpstats.data_loader.stats_nba_v3.web 0022500521 -o game.json --save-responses raw
```

This requests `playbyplayv3` and `boxscoretraditionalv3` from stats.nba.com, or stats.wnba.com for a WNBA game ID, builds the adapter's context from the box score, parses the game with the original engine and writes the possessions as JSON. `--save-responses` keeps the raw responses used. To parse saved responses offline instead, pass `--pbp FILE --boxscore FILE`, and `--live FILE` for a saved live play-by-play. Offline, a game that needs a period-start box score or the live play-by-play stops and names that request.

How the context and starters are built:

- **Roster:** box-score names, plus the play-by-play's own ID-bound actor names, description aliases and unaccented variants.
- **Starters:** the original's own inference. If inference needs its period-start box score, the tool fetches the original's exact `boxscoretraditionalv2` request and records it as evidence.
- **Unresolved names:** only when the roster alone can't resolve a description name, such as a tip to one of two same-named players, does the tool retry with the box score's first-period starters as on-court evidence. The JSON then lists them under `supplied_period_starters`.
- **Undecided jump balls:** V3 leaves a team-won jump ball's description blank, and a tip can name a surname two players share that the starters do not separate. For these the tool fetches the league's live play-by-play from the original's own live source and records it. The adapter reads only that jump ball's jumpers and recipient or team, under the same action number, and checks each against V3.
- **Missing names:** a description name the box score lacks, such as a given name, needs a reviewed `--alias PERSON_ID=NAME`.
- **Reviewed corrections:** `pbpstats/data_loader/stats_nba_v3/reviewed_corrections.json`, loaded as `web.REVIEWED_CORRECTIONS`, is the override file for games the original cannot parse as recorded. Each entry names the play-by-play bytes it was reviewed against and what the review found. Its corrections use the original's override-file schema, or make the original's own remedy of editing the play-by-play file: `event_order.json` moves one event to just before another at the same clock, `event_subtypes.json` gives the V3 subtype an event should have recorded, such as a free throw's attempt number or a turnover, foul, rebound or violation type, and `event_clocks.json` changes only the tenths within the recorded second. The tool supplies each entry as `V3Overrides` only for the exact play-by-play bytes reviewed, and refuses other bytes for that game. There are nine. One gives the 4th-quarter starters of WNBA game `1042600201`. Eight follow video review of 2025-26 games: technical free throws shot before the last regular free throw (`0022500169`, `0022500775`); made free throws logged 1 of 1 that were 1 of 2, the second attempt ending in a violation (`0022500054`, `0022501009`); a lane-violation turnover left without a subtype (`0022500944`); an away-from-play foul that replay changed to a personal foul (`0022501070`); a shooter's lane violation logged with a placeholder team rebound (`0022501079`); and an and-one foul and free throw logged a tenth after the basket (`0022500684`).

The JSON has:

- **Per game:** final score, credited possessions per team, capabilities, diagnostics and source URLs with SHA-256 hashes.
- **Per possession:** period, number, offense and defense, start and end clock, start score margin, start type, whether it counts, and the lineups the original credits.
- **Per event:** type, clock, description, team, players, score, lineups and V3 source rows.

Detailed per-player statistics stay gated, as the adapter's capabilities state.

From Python, with the checkout root as the working directory or on `PYTHONPATH`:

```python
from pathlib import Path

from pbpstats.data_loader.stats_nba_v3 import web

loader = web.save_game("0022500521", Path("game.json"), responses=Path("raw"))
```

`save_game` is the command's own per-game path, and Cheeseburger's batch script calls it too:

- It fetches the game, or reuses saved responses passed as `raw`.
- It applies reviewed corrections and writes the JSON atomically, indented four spaces.
- It keeps the raw responses even when a game is rejected.
- Pass a `requests` session as `session` to pace or retry requests.
- With `skip_absent_aliases=True`, aliases apply only to players in the game's box score.

`fetch_game`, `load_game` and `possessions_json` remain available for finer control.

Games are rejected rather than guessed when V3 lacks a fact or the original rejects them. Offline over the 2025-26 captures, the tool parses 1,089 games; 44 of them use the held-ball extension. The 1,082 that the corpus audit also passes have the same credited possessions there; the other seven use reviewed corrections, which the corpus audit does not apply. The rest are:

- 97 team-won jump balls;
- 20 names that need an alias or an on-court witness;
- 3 order-fallback cases;
- 1 heave;
- 3 games needing the period-start box score, which is fetched when online;
- 17 captures without the inputs.

The captures hold no live play-by-play. With it for the jump balls V3 leaves undecided, as the tool fetches online, 1,197 games parse and none of the 1,089 above changes. No team-won jump ball remains and 15 of the 20 names resolve. The other games stop at later checks: 6 period-start box scores, 5 names, 3 order fallbacks and 1 heave. In one game, `0022500974`, the live feed numbers an overtime jump ball 799 where V3 has 804, and the adapter does not match it by clock.

## Current adapter

`pbpstats.data_loader.stats_nba_v3.StatsNbaV3PossessionLoader` accepts V3 source bytes and a `V3Context` containing source provenance, a matching PBP hash, an NBA or WNBA game ID with its two teams, a recorded roster with names, and any explicitly supplied period starters. Omitted periods use original event inference and scoped starter overrides, with optional `starter_boxscores={period: V3StarterBoxscore(...)}` for recorded interval responses when recovery is needed. It builds the **original** Stats enhanced-event classes through their factory and reuses original enhancement, order repairs, possession decisions and attribution. Two versioned extensions go beyond the original, each reported as a capability and a diagnostic wherever it applies: recorded NBA team heaves, and held-ball turnovers recorded after their jump ball. The [contract](docs/v3-parity-contract.md) defines both.

The original loader's repair input is a temporary in-memory constructor projection. Source bytes, raw rows and per-event source indices remain separate. File-writing repair hooks record diagnostics instead. Optional `V3Overrides` supplies recorded legacy bad-possession/boundary correction files and reviewed play-by-play edits; optional `V3EventOrder` supplies a recorded provider response for the original ordering fallback; optional `V3JumpBallEvidence` supplies a recorded live play-by-play for jump balls V3 leaves undecided. All require provenance and the exact PBP hash. Missing provider evidence still blocks recovery without making a network call. Existing V2 loaders are untouched.

The [starter recovery continuation](docs/v3-starter-recovery-progress.md) documents 70 matching declared observations, including 29 new full-loader starter cases, exact exception classes/messages/context, scoped overrides, repairs and selected HTTP/JSON failures. Broader source/API and ingestion behavior remain open gates. The [initial exception checkpoint](docs/v3-exception-parity-progress.md) preserves the earlier 41-case results.

This is an **experimental, bounded NBA and WNBA adapter**, not the replacement for Cheeseburger's game API. Unknown event vocabulary/participants fail explicitly. Detailed statistics are unavailable at the adapter's aggregate API until attribution completeness is implemented; original event objects are exposed for compatibility research and their direct statistics must not be treated as complete V3 outputs. `full_game_validated` stays false because schedule, official-box validation and the full evidence contract are not implemented here.

Synthetic sequence checks explicitly bypass full source-order and alternating-possession validation, matching the original synthetic worker's scope. The recorded-game checks run both validations. Passing a synthetic case is not a full-game acceptance claim.
