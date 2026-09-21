"""Official page-derived roster, loaded through the production validator."""

from pathlib import Path
from types import SimpleNamespace

from pbpstats.data_loader.stats_nba_v3.boxscore import (
    StatsNbaV3BoxscoreLoader,
    V3BoxscoreSourceData,
)

DATA = Path(__file__).resolve().parent / "data"


def recorded_boxscore():
    prefix = "game_details/stats_v3_boxscore_0021900001"
    box, evidence = prefix + ".json", prefix + ".evidence.json"
    source = V3BoxscoreSourceData(
        (DATA / box).read_bytes(), (DATA / evidence).read_bytes(), box, evidence
    )
    return StatsNbaV3BoxscoreLoader(
        "0021900001", SimpleNamespace(load_data=lambda _: source)
    )
