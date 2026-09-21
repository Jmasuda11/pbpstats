# Official native V3 league fixtures

See `docs/v3-leagues.rst` for the validation matrix, league rules, and known rejection cases.

`manifest.json` identifies eleven final games, original URLs and retrieval times, original HTML/script checksums, and checksums of every committed raw/evidence extract. Original HTML is not committed. NBA/WNBA action objects and full team player arrays are unchanged page extracts with explicit envelopes; G League responses are original endpoint bytes with their request metadata retained. `official_game.json` contains factual final-game observations only.

`game_details/*.evidence.json` binds roster completeness and supported spelling aliases to the box-score bytes; aliases cite explicit identity/name pairs in the recorded PBP, including ASCII description spellings and Xu Han's displayed `Xu`. The Cleveland coach entry has separately documented team provenance and never enters the player roster.

Five `lineups.evidence.json` files contain reviewed per-period witnesses, full batch coverage, context/snapshot fingerprints, and (where needed) explicit assertions about already-applied replay outcomes. Four games complete the possession pipeline. Bucks-Raptors reconciles player minutes and points but intentionally fails possession control validation at rows 26-27. Other rejected captures retain their missing evidence rather than fabricated sidecars.

Later-period starters do not come from complete roster arrays or previous period endings. On-court witnesses precede a player's first entrance in the full substitution stream, and independent published minutes validate the resulting lineups. The unobserved Stockton OT player's 153-second residual is separately recorded and tested against all other roster candidates. Q1 alone also agrees with the official position markers.

Tests disable network access, verify file hashes, compare every player box-score total and minute count for successful games, compare period scores, and assert specific failures for the other captures. Possession counts are regression values under the shared engine's convention; they are not claimed to be official box-score measurements.
