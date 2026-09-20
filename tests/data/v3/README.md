# Stats V3 reference fixtures

These files are recorded inputs for developing the V3 provider. They do not
establish current endpoint availability or prove that a possession parser is
correct. No V3 provider is exposed by this change.

`manifest.json` records each fixture's origin, SHA-256, game, scope, and available
response metadata. Metadata timestamps are not independently verified capture
times. The two complete snapshots are copied byte-for-byte; `.gitattributes`
prevents Git's line-ending conversion from changing their checksums.

| Fixture in `../pbp/` | Scope and purpose |
| --- | --- |
| `stats_v3_0021900001.json` | User-archived snapshot, 596 actions. Aligns with the existing V2 `stats_0021900001.json` fixture's 573 event numbers. Includes overtime, split blocks/steals, fractional clocks, and a lane-violation ordering difference. |
| `stats_v3_0022400001.json` | Complete 475-action reference published by [swar/nba_api](https://github.com/swar/nba_api) at the immutable commit and URL recorded in the manifest. Provides a second snapshot without relying on the local archive's provenance. |
| `stats_v3_0042500317_heaves_excerpt.json` | **Incomplete game: eight actions only.** Two team-heave sequences selected from a user-archived snapshot. Source action indices are zero-based; row contents, IDs, metadata, and relative order are preserved. The JSON serialization differs from the full source, whose hash is also recorded. |

The original archive capture process was not verified. The first fixture's V2
counterpart is the repository's corrected-order fixture; `raw_stats_0021900001.json`
has a different order. Neither is an infallible oracle for V3.

The executable examples in `tests/test_v3_data_contract.py` describe these
snapshots, not a universal NBA schema. In particular, action-number alignment in
one game does not establish stable cross-provider or cross-snapshot identity.
Tests use repository-relative fixtures and do not require the original archive,
research directory, or NBA network access.

Keep source inputs unchanged when implementing repairs. Record derived order and
participant inferences separately. Replacement snapshots need updated provenance
and reviewed expectations, not silently updated hashes to make tests pass.
