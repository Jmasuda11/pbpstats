# Paired 2024-25 V2/V3 season evidence — October 5, 2026

This continuation adds the V3 export for the same 2024-25 regular-season games as the pinned V2 export and pairs the two event by event. It changes no adapter behavior. It is factual decoding evidence and the input for a full-game differential, not an adapter parity result.

## Evidence

The V3 export comes from [shufinskiy/nba_data at revision e829d4678be1e075f99e5d41a1c5f97089be446b](https://github.com/shufinskiy/nba_data/tree/e829d4678be1e075f99e5d41a1c5f97089be446b), the same revision as the V2 export. It is stored at `tests/parity/data/nba_data/nbastatsv3_2024.tar.xz`: 8,781,060 bytes, SHA-256 `38fb8bfb43be8db3d47576600f32f25d89cc3cc05ebac77a51f4db42faf0b841`. Its git blob `7d4cd35da84aa43f677364c3e56a050038f5c850` matches the pinned tree listing; the existing V2 export's blob was rechecked against the same listing. The single member, `nbastatsv3_2024.csv`, has 606,538 rows for 1,230 games. The already pinned `loading-utils.R` contains its collector, `load_playbyplayv3`.

`tests/parity/paired-season-evidence.json` records both archives, the provenance files, a fidelity witness and the only normalizations: restore ten-character game IDs, type the V3 integer fields, and strip export padding from `actionType` and `subType`. The export's 475 rows for `0022400001` equal the separately recorded V3 JSON response exactly after normalization. Without the padding strip, one row differs.

Both exports are community CSV exports, not raw NBA JSON or a behavioral oracle. The pinned original engine remains the oracle.

## Pinned facts

`tests/parity/paired-season-2024.json` pins these results; `tests/parity/test_paired_season.py` recomputes them from the archives.

| Fact | Result |
| --- | --- |
| Games in both exports | 1,230 of 1,230 |
| Events paired by event number | 574,358 of 574,358; none unmatched on either side |
| Same period; same primary actor | 574,358 each |
| V3 steal and block rows against V2 `PLAYER2`/`PLAYER3` | 20,184 of 20,184; 11,996 of 11,996 |
| V3 labels with more than one V2 code | 0 of 188 |
| Clock | Equal for 521,771 whole-second events; V2 is the floor of V3 for all 52,587 fractional events |
| Event order | Identical in 159 games. The other 1,071 differ only inside one clock instant: 2,660 instants, 2,733 moved events, no cross-instant differences |
| V2 duplicate rows | `0022400480` events 303 and 308 appear twice, identically |

V3 lacks two facts that V2 records. V2 names the fouled player for 45,826 of 46,916 fouls; the V3 stats feed has no equivalent field. For 98 jump balls the V3 description is blank, while V2 still identifies the opposing jumper and the recipient or team. The league's live play-by-play records these facts under the same action numbers: `tools/parity/live_jump_balls.py` finds all 2,193 V2 jump balls agreeing with their live actions, 2,093 player tips and 100 team recoveries (`.parity/live-jump-balls-nba-2024.json`, SHA-256 `08b174a236782b15e3746042c6b2f7df375a41066ce6414158941d5f29f626f4`). The adapter reads them as [recorded evidence](v3-parity-contract.md).

The held-ball pattern is not new to 2025-26. In 184 cases (164 games), a jump ball is followed by a lost-ball turnover and a steal between the two jumpers; 55 occur at a later clock. V2 records the same lost-ball turnover with a stealer in all 184 cases. The original engine sees this pattern on both feeds. Its own rule covers the same-clock cases. Since October 6, 2026, the later-clock cases use the [held-ball extension](v3-parity-contract.md) wherever the original would change possession at the jump ball.

Same-instant reordering mostly involves substitutions, free throws, shooting fouls and rebounds.

## Decoder comparison

The tool decodes one real sample per label with the candidate's own `DecodedV3`. Before the corrections below, 156 labels matched V2, 8 differed and 24 were rejected. The decoder now produces the recorded code for all 188 labels; `test_paired_season.py` asserts this for every label, and checks every decoder table entry against the pinned codes. Inbound, Personal Block and Shooting Block are the only table entries absent from the paired evidence; they keep the original's own named codes and are declared as unobserved.

Codes the decoder produced before the corrections:

| V3 label | Recorded V2 code (events) | Decoder |
| --- | --- | --- |
| Rebound / Normal Rebound | 4/1 (5,904) | 4/0 |
| Timeout / Regular | 9/1 (13,343) | 9/0 |
| Timeout / Coach Challenge | 9/7 (335) | 9/0 |
| Made and Missed Shot / Driving Dunk Shot | 1/9 and 2/9 (1,984) | 49 |
| Instant Replay / Overturn Ruling | 18/1 (234) | 18/5 |
| Instant Replay / Ruling Stands | 18/3 (160) | 18/6 |
| Foul / Hanging Technical | 6/13 (11) | 6/12 |

Every label rejected before the corrections has a single recorded code:

- **Replays and ejections:** Replay Center 18/7, Altercation Ruling 18/2, Ejection Other 11/4.
- **Jump balls:** coach-challenge jump ball 10/1. The `(CC) ` marker appears exactly on coach-challenge descriptions and is no longer parsed as part of a name.
- **Fouls:** Flopping 32, Bench 33, Excess Timeout Technical 25, Non-Unsportsmanlike Technical 12, Too Many Players Technical 30, blank subtype 0.
- **Turnovers:** Double Dribble 6, Discontinue Dribble 7, 5 Second Violation 9, Inbound 12, Jump Ball Violation 18, Illegal Assist 20, Palming 21, 10 Second Violaton 24, Punched Ball 33, Basket from Below 35, Illegal Screen 36, Excess Timeout 42, Too Many Players 44, blank subtype 0.

Of the differing codes, only the rebound code reaches original decisions, through `is_placeholder` and `is_real_rebound`. Original decision methods do not read timeout, replay, jump-ball or shot subtype codes, and Hanging Technical codes 12 and 13 are both technicals. Exposed event codes still differ from V2.

Among the rejected labels, a code-0 turnover is `is_no_turnover` and does not end a possession. Flopping 32 and Bench 33 are neither technicals nor personal fouls in the original.

The five historical shot aliases are not ambiguous in this season. Driving Dunk Shot is recorded as 9, not the previously retained 49; `shot-vocabulary.json` now uses the paired 9 observation, which is the same event as the mapping's V3 observation, and keeps 49 as a historical alias. Driving Layup 6, Running Jump Shot 2, Hook Shot 3 and Jump Shot 1 match the decoder. Codes 42, 45, 46, 49 and 55 remain historical observations.

## Actors outside the player roster

V3's `personId` and `teamId` equal V2's `PLAYER1_ID` and `PLAYER1_TEAM_ID` for all 574,358 paired events (pinned as `actor_teams_equal`). In both feeds, technical fouls, double technicals and ejections can name coaches, with no team, and inactive players, with their team. V2 marks 153 coach rows with no team. The original Stats event then treats a teamless person ID as the event's team. The decoder now passes those three event kinds' recorded pair through as V2 records it, with a `non_roster_actor` diagnostic. Any other event by a person outside the roster is still rejected.

## Blank jump-ball descriptions

The 100 V3 jump balls without a parseable description are exactly the 100 whose V2 `PLAYER3_ID` is a team: tips won by a team rather than a player. V3 omits both the opposing jumper and the winning team there, so these events remain rejected until separate evidence supplies them.

## Next

The [season differential](v3-season-differential.md) runs the original engine on each V2 game and the adapter on the paired V3 game.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -B -m tools.parity.paired_season
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/parity/test_paired_season.py
```

The tool writes `.parity/paired-season-2024.json` and prints the join and decoder summary. `--write-expected` explicitly replaces the pinned facts; it never runs automatically.
