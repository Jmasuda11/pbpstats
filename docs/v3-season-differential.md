# Season differential: original V2 engine versus the V3 adapter — October 5, 2026

`tools/parity/season_differential.py` runs every game of the paired 2024-25 season twice: the pinned original (`e7ccf2f`) on the game's V2 export through the original full file loader, and the candidate adapter on the same game's V3 export. Each side runs in its own isolated process with network access disabled, and the comparison is game by game. This is the first full-game parity measurement on real games; earlier evidence was synthetic scenarios, one paired 2019 game and per-family suites.

## Method

The V2 side rebuilds the recorded V2 JSON shape from the export: integer columns typed and blank cells as `null`. A test round-trips a recorded V2 response through that rule exactly. The original then runs unchanged: its order repairs, starter inference, possession splitting, alternation check and statistics. When it would need the network, for the data.nba.com order fallback or the boxscore starter fallback, the game is a rejection with that category.

The V3 side reads no V2 fact. The context is built from V3 alone:

- **Teams:** from the `location` field.
- **Roster:** players who act in the game, with names from their own rows and actor descriptions. A substitute who never acts is named only in a substitution description; such a name is bound to the unique same-team player with that name among the season's other V3 actor rows. This happened in 296 games, and ambiguous names stay unresolved.
- **Starters:** none are supplied, so the adapter runs the original starter inference just as the V2 side does.

Production uses box-score rosters instead.

The V3 side runs in three modes:

| Mode | Clocks | Order | Use |
| --- | --- | --- | --- |
| `exact` | V3 tenths | V3 | Production-equivalent input |
| `floor` | Floored to whole seconds, as V2 records them | V3 | Isolates the clock policy |
| `floor_v2_order` | Floored | V2's order within each clock instant | Diagnostic of translation fidelity; reads one V2 fact |

The paired evidence pins both projections: V2's clock is the floor of V3's for all 574,358 events, and the two feeds differ in order only inside a clock instant.

Two shared inputs and gaps are declared:

- **Shot coordinates:** the pinned evidence has no V2 shot chart, so the original's shot-chart files are written from the V3 export's `xLegacy`/`yLegacy`. Both sides therefore see identical coordinates.
- **Fouled player:** V3 does not record it. Foul `player3_id` and fouls-drawn statistics are compared separately, as a known gap, rather than masking other differences.

Each comparable game is compared on:

- possession credits with lineup IDs;
- possessions, with membership, offense, boundaries, start type and margin, and counting;
- every event's lineups, score, ending, offense, counting, computed properties, relations, base statistics and V2 type/action code;
- exact Decimal player and lineup statistic totals from the original per-event statistics.

A time- and same-instant-order-blind decision view separates decisions from timestamps.

## Results

Report: `.parity/season-differential-2024.json`, SHA-256 `3d7ef1e3a7aefbac1110fafaad3f537e630dc20512506b278afed994a8dba285`. Its implementation hashes match the current adapter and tooling. It was re-run after the adapter's `get_team_ids` guard (see the contract) and again after the October 6 code-review fixes. Per-game results were identical in all three modes each time, and no 2024-25 game reaches that defect. Double-foul participants are compared where V3 names both players.

The original completed 1,051 of 1,230 games offline. Both sides completed 937 games in every mode: 187,309 possessions, of which the original credits 185,402.

| Comparable games (937) | Equivalent facts | V3 order, floored clocks | Exact V3 |
| --- | ---: | ---: | ---: |
| Identical | **937** | 565 | 0 |
| Same decisions, other values differ | 0 | 4 | 191 |
| Different decisions | **0** | 368 | 746 |
| Games with different credited possession counts | 0 | 0 | 339 |
| Net credited possessions, V3 minus V2 | 0 | 0 | +414 |
| Possessions whose credited lineup row differs | 0 | 69 in 61 games | 483 in 377 games |
| Games with any event-code difference | 0 | 0 | 0 |

With equivalent facts, the adapter reproduces the original exactly on every comparable game. That covers possession credits and lineups, membership, offense, start types, every event's computed properties and relations, V2 event codes, and exact player and lineup statistic totals. The fouled-player gap is the only exclusion, and it differs in all 937 games.

Every remaining difference comes from a different input fact:

- **Same-instant order.** The feeds order events within one clock instant differently in 1,071 games, mostly substitutions around free-throw trips. With V3's order, the zero-second substitution often moves to the other side of a possession boundary. Possession membership then differs in 344 games and event offense in 277. Credited counts never change. The credited lineup changes for 69 possessions, typically when the last free throw is missed and the rebound's lineup decides the credit. No simple rule recovers V2's order: V2 places substitutions both between and after free throws, while V3 follows event-number order in 85% of reordered instants.
- **Clock precision.** Tenths of a second change final-second decisions. Real-rebound classification differs in 326 games, possession counting in 324 and membership in 292. V3 credits 414 more possessions (+0.22%), as in the paired 2019 game's 2.8- and 2.1-second starts.

## Rejections

Rejections never count as passes. With equivalent facts:

| Outcome | Games | Cause |
| --- | ---: | --- |
| Both need the data.nba.com order fallback | 83 | Unavailable offline |
| Both fail the alternation check | 55 | Original behavior on V2, including held-ball turnovers at a later clock |
| Both need the boxscore starter fallback | 16 | Unavailable offline |
| V3 only: team-won jump ball | 71 | V3 omits the opposing jumper and winning team |
| V3 only: unresolved name | 42 | This comparison's V3-actor roster; production uses the box score |
| V3 only: boxscore starter fallback | 1 | Less inference evidence without fouled players |
| Different rejections | 25 | V3's missing jump-ball or name fact comes first |

With V3's own order, 79 games that the original needs the data.nba.com fallback for complete without it, and 3 V2 alternation failures disappear.

## Why 69 possessions credit a different lineup

The original credits each possession, as OffPoss/DefPoss rows with lineup IDs, at the possession's ending event. It uses the lineup on the floor at that event, except that a free-throw ending uses the lineup at the foul (`event_for_efficiency_stats`). Events at one clock instant are processed in feed order. A substitution listed before the crediting event therefore credits the incoming player; listed after, it credits the outgoing player. Credited counts never change. Each case moves one possession for one team between two lineups, with the related lineup statistics; seconds played do not change.

All 69 cases were re-run with full records (`--game` for the 61 games); every one disappears with V2's order:

| Crediting event | Cases | Which feed lists the substitution before it |
| --- | ---: | --- |
| Defensive rebound of a missed last free throw | 59 | V3 in 58, V2 in 1 |
| Turnover | 6 | V2 in 4, V3 in 2 |
| Foul before a free-throw ending | 3 | Both list one substitution first; V3 also lists a second substitution before the foul |
| Rebound of a field-goal miss | 1 | V2 |

The offensive team's lineup changes in 35 cases and the defense's in 34.

Example, `0022400021`, Q3 5:26: Mobley's shooting foul; Tatum makes free throw 1 of 2, misses 2 of 2, and Porter Jr. rebounds. V3 lists "SUB: Hauser FOR Brown" between the free throws, while V2 lists it after the rebound. The Celtics' possession ends at the rebound, so the original credits it to the lineup with Brown, and the adapter to the lineup with Hauser.

Substitutions can only happen while the ball is dead. In the dominant case the rebound puts the ball in play, and nothing else is recorded at that second afterwards, so V3's placement between the free throws is the plausible one in 58 cases. In the three foul cases, V2's placement after the whistle is the plausible one, as it is in the single reversed rebound case. The turnover and field-goal-rebound cases depend on stoppages that neither feed records.

## Decisions this measures

1. **Clock policy: decided October 5, 2026.** The adapter keeps exact V3 clocks. They are more precise but change 746 games' decisions and add 414 credited possessions. The floor projection remains only a comparison diagnostic.
2. **Order policy: decided October 6, 2026.** The adapter keeps V3's recorded same-instant order and the original crediting rule. Free-throw statistics follow the foul-time lineup, and a possession is credited at its ending event, which uses the foul-time lineup only when the ending event is a free throw. Differences from V2's order are treated as V2 recording quality. With V3's order, possession membership differs in 344 games and credited lineups for 69 possessions; no simple rule reproduces V2's order.

With both policies decided, the `exact` mode is the target behavior. Its differences from the original on V2 come from those two accepted source facts. Separately, V3 omits the fouled player and the winner of team-won jump balls.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.season_differential
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity/test_season_differential.py
```

The full run takes about 30 minutes; `--limit N` or `--game ID` runs a subset and `--keep DIR` retains worker inputs and per-game records. `test_season_differential.py` checks the reconstruction rules, the clock projection against every recorded V2 clock, the order diagnostic and V3-only rosters. It also runs three full games end to end: equivalent facts are identical, and game `0022400001` shows the free-throw substitution moving between possessions.
