# V3 parser parity implementation plan

Prepared October 2, 2026. This is an implementation plan; it does not change parser behavior or authorize a production backfill.

Implementation has started in this checkout on `feat/v3-parity`. See [current progress](v3-parity-progress.md) for executed checks, the first adapter slice, and remaining phases. Cheeseburger's parser selection has not changed.

**Goal**

Make V3 another input adapter for the original pbpstats behavior. Reuse one implementation of enhanced-event decisions, possession grouping, and attribution. Preserve V3 source evidence and explain differences caused by different input facts.

```text
V2 rows -> V2 decoding and source preparation --+
                                              +-> shared event enhancement -> shared possessions -> statistics
V3 rows -> V3 decoding and source preparation --+
```

The compatibility requirement is: equivalent supported facts and context produce identical event decisions and possession outputs under the pinned V2 behavior. Historical output equality is a separate check when feeds disagree about clocks, participants, order, or corrections. A rejected or untestable game does not count as a parity success.

Exact parity includes the original's observable quirks. Corrections and newer league behavior require explicit versioning and separate expectations. Preserve exact V3 clocks; any optional historical-clock projection must be a named comparison policy that leaves the raw recording intact.

**Recommended workspace**

Use a separate fresh clone of the existing fork for implementation, with an implementation branch based on upstream revision `e7ccf2fb6326da630a3cf1665aac964a1e108f4c`. Keep the existing checkout, research, recordings, and import artifacts as references. A new clone of the fork's current default branch would still contain the previous attempt; selecting the starting revision is essential. Retain the fork's Git history and upstream remote rather than creating an unrelated repository.

Use an isolated Python environment so editable installs cannot cause tests or Cheeseburger to import the wrong checkout. Verify and record the imported package path in comparison runs. Bring over reviewed recordings, scenarios, and diagnostics first; transfer implementation only when its responsibility and compatibility tests are established. This workspace setup has now been performed; implementation status is recorded separately above.

**Starting evidence**

- Use upstream revision `e7ccf2fb6326da630a3cf1665aac964a1e108f4c` as the primary original-V2 reference. Inspection of local history confirmed that the audit's reference `05a5f02a844b9e055e9edd470d73c8479fa061cf` already includes early V3 work and changes to legacy free-throw attribute handling, Stats event initialization, and Live clock parsing. Retain that audit revision as a secondary checkpoint; do not label it untouched upstream.
- The October 2 checks compared current V3 with `use_v2_rules=True` against saved V2 snapshots from that audit reference for 145 existing synthetic scenarios: 143 matched and two differed. These snapshots cover boundaries, offense, count flags, possession-credit lineups, final score, and event count; they are not exhaustive API or ingestion comparisons and must be rerun against the untouched upstream reference.
- Remaining synthetic differences are free-throw lineup attribution after an intervening technical foul, and an interior jump during the first possession.
- The current paired-game test passes with 227 matching boundaries. V3 credits two additional possessions because 2.8- and 2.1-second starts were recorded as 2 seconds in V2.
- Detailed native V3 event statistics are currently unavailable. Possession/time support must not be described as full statistical parity.

**Phase 1 — Freeze the baseline and define the supported contract**

1. Create the separate implementation checkout and isolated environment. Pin the untouched upstream V2 revision, prior audit revision, and current V3 revision, dependencies, configuration, and all evidence needed to reproduce each path. Record source hashes and prevent reference artifacts from being silently regenerated. Record existing upstream test failures separately rather than silently fixing the reference.
2. Inventory archived V2 games, paired V2/V3 recordings, synthetic encodings, current accepted games, and rejected games. Record fixture provenance, source repairs, overrides, starters, roster inputs, and capture completeness.
3. Define the required possession output contract: event membership/order, offense/defense, boundaries, period links, start labels, score margins, count eligibility, time, and player/opponent lineup attribution. Inventory public properties consumed by Cheeseburger and legacy pbpstats consumers.
4. Classify every known difference as adapter error, behavioral divergence, source-fact difference, missing evidence, legacy defect, or explicit league extension. Record the known free-throw and jump-ball cases as behavioral divergences that must match the original in compatibility behavior.
5. Define separate acceptance gates for parser compatibility, source completeness, and publication validation. Keep current validation protections while making their coverage impact visible.

Deliverables: immutable reference manifest, fixture inventory, compatibility contract, and initial difference register.

Exit gate: both reference and candidate runs are reproducible from recorded inputs; the required outputs and treatment of every known difference are explicit.

**Phase 2 — Build an independent differential test harness**

1. Promote the useful code in `nbastats/research/v3_logic_audit` into maintained test tooling. Run the pinned original in a separate process/package environment from the candidate; disable network access in deterministic tests.
2. Add normalized snapshots at three boundaries: decoded event facts; enhanced-event properties/context; possession outputs and supported statistics. Use an explicit property inventory rather than assuming object dictionaries expose computed behavior.
3. Match events through source lineage and semantic correspondence. Account for one V3 action represented by multiple raw rows, and administrative ordering differences; do not align only by list position or assume cross-provider event IDs always match.
4. Report the first differing property, surrounding events, raw source indices, input hashes, and parser versions. Separate input differences from decisions made on equivalent inputs.
5. Compare original V2 against current V2 as well as original V2 against V3. Retain independently encoded synthetic feeds and independent accounting assertions so the adapter cannot manufacture its own expected results.
6. Add deterministic CI cases and a larger offline corpus command. Measure match/mismatch/rejection/missing-evidence counts against the complete selected corpus, including previously failed games.

Deliverables: reference runner, snapshots, readable difference reports, CI checks, and offline audit command.

Exit gate: the harness reproduces both known behavioral differences and the fractional-clock source difference, and detects deliberately changed boundaries and lineup credits.

**Phase 3 — Establish a thin V3 adapter and the shared event contract**

1. Audit existing shared classes, Stats V2 classes, V3 classes, and their inheritance/property resolution. Assign each property to source decoding, contextual enhancement, basketball behavior, or validation. Include methods still embedded in V2-specific classes.
2. Define the smallest existing-event-compatible contract for event type/subtype semantics, participants and roles, outcome/value, free-throw position, clock, team, roster/starters, ordering, and provenance. Preserve absent, unknown, ambiguous, and intentionally team-only identities distinctly.
3. Keep V3 raw loading, grouping, participant resolution, source preservation, and recorded context. Translate these facts into the shared event contract. Do not invent numeric V2 action codes or participant IDs for unsupported semantics.
4. Introduce the candidate path beside the current entry point for controlled comparisons. Select it explicitly, and record its behavior version in outputs/evidence. Avoid silently redefining `use_v2_rules=True` as a claim of exact compatibility.
5. Prove basic made/missed shots, ordinary turnovers, substitutions, period markers, and simple rebounds through the candidate path. Preserve legacy imports, event identities where required, and public constructor behavior.

Deliverables: documented event contract, property ownership map, and executable candidate adapter for ordinary sequences.

Exit gate: ordinary equivalent events exercise the same decision methods in both providers, raw-row coverage is complete, and existing V2/Data/Live behavior remains unchanged on its regression fixtures.

**Phase 4 — Consolidate enhanced-event behavior and possession decisions**

Implement in small changes, each with a differential regression before moving to the next family:

1. Share event linking, score accumulation, foul/penalty context, lineup transitions, and efficiency-lineup selection. Keep source-specific representation repairs in adapters; share repairs that implement the same cross-event behavior. Retain original and processing order separately.
2. Share free-throw/foul association, trip interpretation, and-one and retained-ball decisions, and lineup attribution. Resolve the technical-foul attribution divergence in the compatibility path. Keep known legacy misattribution documented as a legacy defect.
3. Share missed-shot association, placeholder/real rebound decisions, offensive/defensive rebound classification, lane handling, and shot/rebound ordering behavior.
4. Share jump-ball ownership and boundaries, first-possession behavior, period-ending behavior, and possession counting. Resolve the first-possession held-ball divergence without folding a bug fix into compatibility work.
5. Use the shared possession grouping, `Possession` objects, links, start labels, and credit calculations. Remove superseded V3 rule overrides as each family passes; retain only justified source decoding and explicitly versioned extensions.
6. Make validation consume the interpreted event stream and diagnostics. Validations may reject contradictory or insufficient inputs, but must not silently choose different basketball outcomes to make checks pass.

Deliverables: one decision implementation per supported rule, a substantially thinner V3 possession loader, and regression fixtures for each migrated family.

Exit gate: zero behavioral mismatches on the equivalent-input corpus, including the two known cases, with all legacy-provider regression checks passing. Listed source differences and unavailable evidence remain visible.

**Phase 5 — Expand real-game coverage and resolve feed gaps**

1. Run every recorded paired game and the full cached V3 corpus, including all 1,230 cached 2025–26 regular-season games in Cheeseburger's existing audit scope. Run supported NBA, WNBA, and G League fixtures under their explicit league/season policy.
2. Group failures by the earliest causal difference. Fix mapping/identity/order errors in the adapter and shared decision errors in the shared implementation. Convert every supported fix into a fixture with relevant counterexamples.
3. Compare all available possession details for paired recordings. For V3-only games, use reviewed sequences, generated equivalent-input cases, and independent score/minute/stat reconciliation; label these as validation rather than direct historical V2 proof.
4. Reconcile source-row accounting, scores, player/team minutes, supported box statistics, period separation, and credit consistency. Document exclusions and tolerances; aggregate equality alone does not establish correct possession segmentation.
5. Classify newer events, such as team-only heaves, as explicit extensions where the original has no equivalent representation. Preserve missing attribution and require evidence for affected outputs.
6. Explain every lost acceptance, new rejection, and changed output relative to the frozen candidate baseline. Do not hide problematic games by shrinking the corpus.

Deliverables: complete corpus report, reviewed difference register, added fixtures, and a capability/coverage matrix.

Exit gate: zero unexplained behavioral differences in the comparable corpus; every coverage change has a reviewed cause, and all required reconciliation checks pass for accepted games. Remaining feed gaps limit the stated support contract.

**Phase 6 — Verify statistics and the public integration contract**

1. Verify possession/time statistics and all public fields needed by Cheeseburger, including start labels, diagnostics, capabilities, exact durations, and provenance.
2. Audit detailed event/player/lineup statistics separately. Reuse shared accounting where evidence is complete; obtain recorded supporting evidence where possible. A missing foul-drawn identity must not silently become an absent foul-drawn credit.
3. Define and test how dependent aggregates expose unavailable or partial attribution. Enable detailed statistics only within that established contract. Full statistical parity cannot be claimed until every required statistic passes on complete equivalent inputs.
4. Version processing behavior, lineup evidence/fingerprints, and persisted import metadata. Ensure evidence prepared for one interpretation cannot silently be consumed by another. Provide an explicit migration/re-preparation path for affected evidence.
5. Exercise Cheeseburger ingestion in a separate test database, including serialization, exact-clock handling, rejected imports, idempotency, capability gates, and selection of the active import. Run repository-required CI checks across supported environments.

Deliverables: verified public API/capability matrix, versioned integration changes, and ingestion regression results.

Exit gate: supported outputs survive end-to-end ingestion without changed meaning; unsupported statistics remain explicitly unavailable. Possession compatibility and full-statistical compatibility have distinct reported status.

**Phase 7 — Roll out and retire duplicated behavior**

1. Run candidate and current parsing side by side on the same immutable captures and evidence. Produce a reviewable report of every changed possession, credited lineup, and acceptance outcome before selecting the candidate for publication.
2. Pin the chosen parser revision, update Cheeseburger's adapter version, and document compatibility behavior, source differences, extensions, and rollback procedure. Switching the default parser must not implicitly rewrite historical imports.
3. Stage representative replacement imports under the new version, verify their output and active-import selection, then expand the reprocessing scope. Preserve prior imports and source captures so rollback can select the previous result.
4. Remove obsolete V3 decision code and transition switches after the replacement path is verified. Keep the original reference runner and differential fixtures as permanent CI protections.

Deliverables: release report, versioned parser/adapter selection, migration and rollback procedure, and removal of duplicate decision implementations.

Exit gate: the shared path is the supported default, versioned imports are reproducible and reversible, and future changes cannot introduce an unexplained V2 compatibility divergence without failing the gate.

**Execution order and completion criteria**

Complete Phases 1 and 2 before changing interpretation. Use the candidate path from Phase 3 to migrate one rule family at a time in Phase 4. Run the small differential suite for every change and expand corpus checks when a family is ready. Phase 5 resolves coverage and evidence gaps; Phases 6 and 7 establish the integration and release contract.

The first implementation milestone is the frozen V2 reference plus a test that exposes each known divergence. The architectural milestone is a V3 adapter whose basketball decisions come from the shared implementation. The release milestone is zero unexplained equivalent-input differences, explicit coverage/statistics limits, and verified versioned ingestion. Historical raw-feed equality is only claimed where the recorded facts support it.
