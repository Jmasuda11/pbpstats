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

Report: `.parity/season-differential-2024.json`, SHA-256 `1584e79e2774e372008b763b285ac5ddc6d634f9f3300f617252c3f860966b3a`, with version 2 of the [held-ball extension](#held-ball-extension). Its implementation hashes match the current adapter and tooling. The extension changes no comparable game in any mode, only rejections. Version 2 changes four: `0022400624` and `0022401094` in every mode, `0022400869` in V3's own order, and `0022401044` with floored clocks. The version 1 report, SHA-256 `878789a6ceb6d595bfea6942063d76978167f08f61be1da94792e01115c0c832`, is kept as `.parity/season-differential-2024-v1.json`. The report before the extension, SHA-256 `bc26cacd3a29ace852888d3b3519f4eed2ba13537634fb25935b6f93860d0165`, kept as `.parity/season-differential-2024-before-held-ball.json`, was re-run three times. The runs followed the adapter's `get_team_ids` guard (see the contract), the October 6 code-review fixes, and [WNBA support](v3-wnba-2025.md) with the fetch tool. Per-game results were identical in all three modes each time, and no 2024-25 game reaches that defect. Double-foul participants are compared where V3 names both players.

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
| Both fail the alternation check | 11 | Original behavior on V2 |
| V2 only: alternation check | 44 | Held-ball turnovers recorded after their jump ball, which the adapter's extension resolves; 55 games failed on both sides before it, and 14 before version 2 |
| Both need the boxscore starter fallback | 16 | Unavailable offline |
| V3 only: team-won jump ball | 71 | V3 omits the opposing jumper and winning team |
| V3 only: unresolved name | 42 | This comparison's V3-actor roster; production uses the box score |
| V3 only: boxscore starter fallback | 1 | Less inference evidence without fouled players |
| Different rejections | 25 | V3's missing jump-ball or name fact comes first |

With V3's own order, 82 games that the original needs the data.nba.com fallback for complete without it (79 before the extension). On exact V3 the adapter fails the alternation check in 9 games, against the original's 67 on V2.

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

## Held-ball extension

The original keeps the possession through a jump ball when the next event is a turnover at the same clock. The league charges a held ball as a turnover once the other team secures the jump ball, sometimes at a later clock. The original then changes possession at the jump ball and fails its alternation check on the turnover, on both feeds. The adapter's versioned held-ball extension applies the same-clock rule at the recorded turnover (see the [contract](v3-parity-contract.md)). Version 2, decided October 7, 2026, also passes over substitutions logged at the jump ball's clock, which are made while play is stopped, and covers a held ball on a player who has just made a steal. With equivalent facts, the extension resolves 44 of the 55 games both sides rejected and changes no comparable game. Version 1 resolved 41. Version 2 adds `0022401094`, where both feeds log a substitution between the jump ball and the turnover, and two held balls after a steal: `0022400624`, and `0022401044`, where the steal and the jump ball share a clock only in whole seconds.

`--held-ball` installs the same module, unchanged, into the original on V2. In that run (`.parity/season-differential-2024-held-ball.json`, SHA-256 `6815ce78ead6df1cb38475f91be0d6016242b8bf2d05048704c9ed3876a1f265`), all 981 comparable games are identical with equivalent facts. Those are the 937 above and the 44 the extension resolves. The extension therefore depends only on facts both feeds record. With it, the original also completes 11 of the 12 games whose V3 side stops earlier at a team-won jump ball. In V3's own order, version 2 also completes `0022400869`, where only V3 logs the substitution between the jump ball and the turnover. The version 1 run, SHA-256 `651f426a01ec9faa0c6e5ff05972cf64a0a98c65e7aecc171d57c15e554ec6e5`, is kept as `.parity/season-differential-2024-held-ball-v1.json`.

## Live jump-ball evidence

V3 omits a team-won jump ball's opposing jumper and team, and names a tip recipient by surname only. The league's live play-by-play records both under the same action numbers. `tools/parity/live_jump_balls.py` compares every V2 jump ball with its live action, independently of the adapter: all 2,193 agree, 2,093 player tips and 100 team recoveries. The adapter reads a recorded live response only for jump balls V3 leaves undecided; see the [contract](v3-parity-contract.md).

`--live DIR` gives the adapter those recorded responses. With them and `--held-ball` (`.parity/season-differential-2024-held-ball-live.json`, SHA-256 `0ec583a671997f01fe77c89e622129aa21b0af27e9c9991961d3357adbcccf79`), all 1,098 comparable games are identical with equivalent facts. The version 1 run, SHA-256 `92e909fbdbd44b32420eb90608edc871c5804d5d62a33846ca96f128a1e92507`, had 1,095 and is kept as `.parity/season-differential-2024-held-ball-live-v1.json`. No game is rejected on V2 alone or for different reasons. The 71 team-won jump balls are all completed, and so are 35 of the 42 unresolved names, which were tip recipients. Seven names stay unresolved because this comparison builds rosters from V3 actors; production uses the box score. One game needs a boxscore starter fallback on V3 only. The other 124 games are rejected on both sides: 94 data.nba.com order fallbacks, 18 boxscore starter fallbacks and 12 alternation failures.

## Decisions this measures

1. **Clock policy: decided October 5, 2026.** The adapter keeps exact V3 clocks. They are more precise but change 746 games' decisions and add 414 credited possessions. The floor projection remains only a comparison diagnostic.
2. **Order policy: decided October 6, 2026.** The adapter keeps V3's recorded same-instant order and the original crediting rule. Free-throw statistics follow the foul-time lineup, and a possession is credited at its ending event, which uses the foul-time lineup only when the ending event is a free throw. Differences from V2's order are treated as V2 recording quality. With V3's order, possession membership differs in 344 games and credited lineups for 69 possessions; no simple rule reproduces V2's order.

With both policies decided, the `exact` mode is the target behavior. Its differences from the original on V2 come from those two accepted source facts and from the held-ball extension, decided October 6, 2026 and extended on October 7 to stoppage substitutions and held balls after a steal. Separately, V3 omits the fouled player and the winner of team-won jump balls.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.season_differential
.\.venv\Scripts\python.exe -B -m tools.parity.season_differential --held-ball
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity/test_season_differential.py
```

The full run takes about 30 minutes; `--limit N` or `--game ID` runs a subset and `--keep DIR` retains worker inputs and per-game records. `test_season_differential.py` checks the reconstruction rules, the clock projection against every recorded V2 clock, the order diagnostic and V3-only rosters. It also runs three full games end to end: equivalent facts are identical, and game `0022400001` shows the free-throw substitution moving between possessions.
