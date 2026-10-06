# Exception and recovery parity — October 3, 2026

This is the initial 41-case checkpoint. The [starter recovery continuation](v3-starter-recovery-progress.md) supersedes its current-status claims with 70 cases, full-constructor starter recovery and a narrow shared I/O extraction. Counts and remaining gates below describe this earlier checkpoint.

The new exception suite compares 41 declared failure/recovery cases against the pinned original in separate, offline processes. Twenty return values and 21 expected exceptions match. Matching an expected exception establishes that fixture's failure behavior; it never counts as an accepted game or full parser parity.

## What changed

`StatsNbaV3PossessionLoader` now accepts two optional evidence inputs:

- `overrides=V3Overrides(files, source, pbp_sha256)` supplies immutable JSON bytes under the original basenames `bad_pbp_possessions.json`, `possession_change_event_overrides.json`, and `non_possession_changing_event_overrides.json`. The original `IntDecoder` preserves NBA game keys and converts numeric period/event/possession values. Original enhanced-event flags and the original alternation check consume these mappings. No override is inferred from a failed parse.
- `event_order=V3EventOrder(source_bytes, source, pbp_sha256)` supplies an independently recorded data.nba.com PBP response. Its game ID, periods and coverage must agree with the V3 input. The original common repair attempts run first; only their provider fallback uses the supplied order. The original provider loader parses the response. The adapter applies that order in memory and records the evidence hash.

Both inputs require provenance and the exact V3 PBP hash. Raw V3 bytes, raw rows and source indices remain intact. Override-file hashes and applied provider-order evidence are included in diagnostics. Neither input enables publication or detailed statistics.

There is one deliberate source-integrity restriction: the provider order must cover each V3 event exactly once. The original fallback can silently drop or duplicate rows with incomplete or duplicate provider IDs; the adapter rejects that evidence. Extra provider-only event IDs are ignored, as in the original. This restriction is an explicit contract difference, not a matching legacy behavior claim.

## Differential coverage

| Boundary | Cases | Coverage |
| --- | ---: | --- |
| Full original file loader versus default V3 loader | 28 | Alternation errors; flagrant exemption and expiration; game/period/possession override scope; force/suppress boundary flags; numeric-string and zero-event overrides; all five rebound-repair branches and technical-before-start repair; provider-order recovery and unresolved rebound failure |
| Original rebound property on independently constructed V2/V3 events | 3 | Made shot and ordinary turnover reject; missed shot associates correctly |
| Original starter inference on independently constructed V2/V3 events | 7 | Too few/many starters; absent override directory/file; wrong game/period/team; valid starter correction |
| Original starter boxscore method on independently constructed V2/V3 events | 3 | Fewer than ten players; unbalanced teams; successful recovery and request parameters |

The original full-loader fixtures use temporary V2 files, complete shot-coordinate inputs and starter-override files. The candidate receives separately encoded V3 facts and explicit starter context. Synthetic provider/boxscore responses replace only oracle transport, not its parsing or basketball logic. The provider-order cases exercise all original repair retries before the fallback.

For expected failures, the comparison checks the fully qualified exception class and exact message. For returns, it checks the declared observations: event order and links, lineups, rebound associations, override flags, possession membership and credit summaries, or the named starter-method result. Each fixture has a declared expected exception and input digest. Identical unexpected crashes, swallowed failures, changed messages/types, altered inputs, missing/duplicate cases and changed possession membership fail the checks.

The inventory test confirms all three exception classes explicitly declared in the original package: `TeamHasBackToBackPossessionsException`, `EventOrderError`, and `InvalidNumberOfStartersException`. This is a class inventory, not proof of every execution path or implicit Python exception.

## Remaining exception gates

1. **V3 starter-loading parity remains incomplete.** The seven inference and three boxscore comparisons invoke shared methods directly. The V3 constructor still requires explicit recorded starters and raises `V3DecodeError` for missing/invalid context. It does not run the original starter-inference → override-file → boxscore-request recovery chain. Recorded context preparation has its own `EvidenceError` boundary. These must not be relabeled as original exception parity.
2. **Generic source/API failures remain outside this adapter's proven contract.** Missing files, malformed payloads, HTTP failures and incidental `KeyError`/`AttributeError` paths need an explicit ingestion/API contract and equivalent-input tests. The named-class inventory does not cover them.
3. **Real correction evidence remains necessary.** The new recovery fixtures are synthetic. No season override or provider order was invented or applied. Games `0022500088` and `0022500660` still raise the original alternation exception and require source review. The input adapter, recorded-evidence preparation, and application integration must be tested together before claiming full exception parity.

## Verification

Run the dedicated comparison with:

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.exceptions
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity
.\.venv\Scripts\python.exe -B -m tools.parity.baseline_tests
```

The dedicated command writes `.parity/exception-parity.json` with reference/candidate package hashes, fixture hashes, harness hashes and every result. This checkpoint's report is preserved as `.parity/exception-parity-initial.json`. Its comparison is separate from the ordinary game-output comparator, which continues to classify rejected games as rejected.

The full season rerun is `.parity/candidate-v3-corpus-exceptions.json`; compare it against `.parity/candidate-v3-corpus-flagrant.json` with `tools.parity.corpus_diff`. The audit remains at 40 research passes, 1,190 blocked games, 43 completed adapter runs, zero crashes and zero publication acceptances. All 1,230 complete per-game records are identical, including source hashes, diagnostics, reconciliation details and the two original alternation failures. `.parity/candidate-v3-corpus.json` now contains the same new report.

Executed validation: **245 parity tests pass** (75 exception-focused tests); the untouched original suite remains **116 passes plus the two exact known fixture failures**. All **183 original production Python files** match the reference manifest. Formatting checks passed on the nine touched/new Python files. No remote CI run or application rollout was performed.

| Local report | SHA-256 |
| --- | --- |
| `.parity/exception-parity-initial.json` | `6d4484b77ca5c0c2f77792fd95e7decd81099f12d46771a439bf779987583ad2` |
| `.parity/candidate-v3-corpus-exceptions.json` | `cd61eb01afd1b6dd96c1217da1f42f795acc734772345d55e5cd16d6eabb3e45` |
| `.parity/corpus-exception-changes.json` | `89cbaba9be554b8df5378f32ee52cccd50dad899fed65fbdef8951d2c09bdf44` |
