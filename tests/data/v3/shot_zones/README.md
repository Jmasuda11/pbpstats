# Official live shot-zone evidence

These four JSON files preserve the original response bytes from the official NBA media-operations live feed; `manifest.json` records origin URLs, capture times and SHA-256 checksums.

They pair with the native V3 fixtures under `../leagues`. Tests join game/action identity, period, clock, player, team, outcome and coordinates, then require the broad and detailed labels to agree before exposing a three-point zone. No source rows have been repaired.

The WNBA captures retain conflicting corner/arc and mid-range labels (39 of 120 three-point attempts); one also has a one-unit xLegacy discrepancy. The G League capture retains zero overtime clocks where native V3 has its elapsed-time counter (two affected three-pointers). The NBA game's 69 three-point attempts all agree. The production adapter preserves per-shot failures and raises on dependent access, while possession/time accounting remains available.

These fixtures establish reported provider-label agreement, not court geometry, independent video truth, full-season support, or period starters. See `docs/v3-shot-zones.rst` for the offline API and limits.
