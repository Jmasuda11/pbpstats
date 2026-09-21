"""Stable provenance labels for checked-in cross-league evidence."""
from pathlib import Path
from types import SimpleNamespace

from pbpstats.data_loader.stats_nba_v3.boxscore.loader import (
    StatsNbaV3BoxscoreLoader,
    V3BoxscoreSourceData,
)
from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)

DATA = Path(__file__).parent / "data/v3/leagues"


def classified(game_id):
    base = DATA / game_id
    box_path = Path(f"game_details/stats_v3_boxscore_{game_id}.json")
    evidence_path = box_path.with_suffix(".evidence.json")
    box = StatsNbaV3BoxscoreLoader(
        game_id,
        SimpleNamespace(
            load_data=lambda _: V3BoxscoreSourceData(
                (base / box_path).read_bytes(),
                (base / evidence_path).read_bytes(),
                box_path.as_posix(),
                evidence_path.as_posix(),
            )
        ),
        league_id=game_id[:2],
    )
    raw = StatsNbaV3PbpLoader(
        game_id,
        StatsNbaV3PbpFileLoader(base, league_id=game_id[:2]),
        league_id=game_id[:2],
    )
    return box, StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(
            raw, box.require_complete_roster(), snapshot_complete=True
        )
    )


def lineup_evidence(game_id):
    import json

    return json.loads((DATA / game_id / "lineups.evidence.json").read_bytes())
