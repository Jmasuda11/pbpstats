# Starter loading and recovery — October 3, 2026

The V3 constructor now runs the original starter recovery sequence for periods omitted from `V3Context.period_starters`: infer from enhanced events, consult scoped starter overrides for non-five inferred sets, then select starters from a recorded boxscore response. The new 29 full-loader differential cases match the pinned original. The combined exception suite has **70 matching observations: 40 returns and 30 expected exceptions**.

## Shared behavior and I/O

Direct reuse of the old starter method was blocked by embedded file/HTTP reads. One candidate production file, `pbpstats/resources/enhanced_pbp/start_of_period.py`, now separates request construction, HTTP response handling and boxscore selection into methods. The V2 request path calls those same methods. Its inference, original sorting, validation messages and failure behavior are preserved by differential tests; the pinned oracle at `e7ccf2fb6326da630a3cf1665aac964a1e108f4c` is untouched.

V3 recovery invokes the original `StatsStartOfPeriod.get_period_starters` dispatcher on an I/O helper. It runs inference on the original enhanced event, applies the legacy game/period/team correction lookup in memory, and uses the shared response selector. Actual enhanced events keep their original classes and methods. No global request hook, event-class replacement or live request is used in the adapter.

The original override precedence is retained: complete five-player inference ignores corrections; a partial correction followed by failure for another team sends the entire period to the boxscore fallback. The recorded boxscore selection still sorts by the seconds component of `MIN`, preserves tie order, takes ten players, and raises the original starter exception for insufficient/unbalanced results. The original non-200 successful-status failure is retained rather than silently repaired.

## Evidence interface

- Supply `missing_period_starters.json` bytes through `V3Overrides`. The original nested `{GameId: {Period: {TeamId: [PlayerIds]}}}` schema and `IntDecoder` key conversion apply. These are recovery overrides, not unconditional replacement lineups.
- Supply `starter_boxscores={period: V3StarterBoxscore(...)}` for fallback responses. Each record carries response bytes, provenance, the exact PBP hash, original request parameters, HTTP status and reason. The request must match the original game and period-start interval when used. A whole-game boxscore is not a substitute for an interval response.
- Periods already present in `context.period_starters` retain the explicit-context path. Invalid supplied context fails validation instead of being silently replaced. Omitted periods can recover independently; caller context and raw source bytes are not mutated.
- Inferred/recovered starters, applied override teams and used response hashes/parameters are recorded in diagnostics. Starter inference reruns when the original order-repair loop rebuilds enhanced events.

Decoding defers substitution-lineup checks when a period has no known starters; the original enhanced stream supplies recovered lineups and the loader then verifies the substitutions. Names still must be unambiguous from the available source evidence. Recovery does not guess a jump-ball participant whose identity depends circularly on the unknown lineup.

## Executed comparisons

The new 29 cases run the **full original file loader and full V3 constructor** with default source-order and alternation validation. The original uses temporary independently encoded V2 files; only its HTTP transport is replaced by synthetic recorded responses. These supplement, rather than relabel, the earlier 13 shared-method tests.

Coverage includes:

- Inference without I/O; valid overrides; unused contradictory overrides/responses; wrong-game/period/team overrides; partial corrections followed by fallback; too many inferred players.
- Boxscore recovery, nine-player and six/four-team failures, original minute sorting, stable ties and extra low-second players.
- Q2/Q4 and first/second overtime request ranges; fractional-clock truncation; opening jump balls; substitutions; recovery repeated during order repair.
- HTTP 404/429/500; malformed JSON; missing result sets; invalid minute text; the original failure on HTTP 204. Exception class, module, exact message and chained inference context match.

Successful comparisons include starters, request parameters/call order, per-event lineups, possession membership and credit summaries. Additional tests reject stale hashes, wrong intervals, invalid evidence/schema, contradictory substitutions and invalid explicit starter context, and verify partial-context recovery and unchanged event methods.

## Validation and corpus result

- **295 parity tests pass**, including **125 focused exception/starter tests**.
- The unchanged original tests run against both the pinned oracle and candidate: **116 passes plus the same two known free-throw fixture failures**, with their exact causes verified.
- All three archived full V2 comparisons and prior synthetic/paired/statistical comparisons remain passing through the full suite.
- Of 183 original production Python files, **182 are byte-identical**; only the starter class has the I/O extraction described above. The reference archive and its source/fixture hashes still verify.
- Formatting checks pass for the 14 touched/new Python files. CI now includes the original regression suite against the candidate package; that workflow has not been run remotely.
- The complete **1,230-game audit has identical per-game records** to the previous checkpoint: 40 research passes, 1,190 blocked, 43 completed adapter runs, zero crashes and zero publication acceptances. The two alternation failures remain blocked. No season correction or new boxscore evidence was manufactured.

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.exceptions
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity
.\.venv\Scripts\python.exe -B -m tools.parity.baseline_tests
.\.venv\Scripts\python.exe -B -m tools.parity.baseline_tests --candidate .
.\.venv\Scripts\python.exe -B -m tools.parity.corpus
```

| Local report | SHA-256 |
| --- | --- |
| `.parity/exception-parity-starters.json` | `fbb4f5a72257585dedd5d48263c29ee40d2b480b391a0fecbf0b06b474cd0a47` |
| `.parity/candidate-v3-corpus-starters.json` | `bab2bfd76b544a6adc958d4097367e9b12d9dd2d087d8d67ed0aa4b4c4983d79` |
| `.parity/corpus-starter-changes.json` | `35ef4ef35ffa0f3bb9587056c8746edeb2ae8486b99af364b7d61bf12eae5bad` |

The default exception/corpus report paths now contain these latest reports. The prior 41-case exception report is preserved as `.parity/exception-parity-initial.json`.

## Still required for full parity

The supported starter recovery path is now compared through constructors, but this is not exhaustive exception or parser parity. Missing recordings raise `V3DecodeError` with the original inference failure as context; stale/provenance-invalid evidence is also an adapter-specific rejection. Existing roster/lineup-integrity checks still reject invalid results that legacy code may tolerate. These evidence boundaries are explicit contract differences.

Generic file/transport/decoding behavior outside the recorded starter-response path, broader malformed-input coverage and application ingestion still need comparison. Real interval evidence is still needed for the six overtime preparation blockers; the season preparer continues to require independently verified context and does not automatically use this new fallback. Recorded corrections for games `0022500088` and `0022500660` remain unreviewed. Event vocabulary, attribution completeness, statistics, additional leagues and application rollout remain separate open gates.
