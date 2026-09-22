"""One deterministic offline entry point for the native V3 possession pipeline."""

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Mapping, Optional, Tuple

from pbpstats.data_loader.abs_data_loader import validate_file_directory
from pbpstats.data_loader.stats_nba_v3.boxscore import (
    StatsNbaV3BoxscoreFileLoader,
    StatsNbaV3BoxscoreLoader,
)
from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
from pbpstats.data_loader.stats_nba_v3.jump_balls import V3JumpBallEvidence
from pbpstats.data_loader.stats_nba_v3.lineups import (
    StatsNbaV3LineupLoader,
    V3LineupEvidence,
)
from pbpstats.data_loader.stats_nba_v3.participants import StatsNbaV3ParticipantLoader
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader
from pbpstats.data_loader.stats_nba_v3.shot_zones import (
    StatsNbaV3ShotZoneLoader,
    V3LiveShotEvidence,
)
from pbpstats.resources.league_rules import V3LeagueRules


@dataclass(frozen=True)
class V3Diagnostic:
    stage: str
    code: str
    message: str
    source_indices: Tuple[int, ...] = ()
    possession_index: Optional[int] = None


class V3GameLoadError(ValueError):
    """A required stage failed; the original exception is retained as the cause."""

    def __init__(self, game_id, diagnostic):
        self.game_id, self.diagnostic = game_id, diagnostic
        super().__init__(
            f"Stats V3 game {game_id}, {diagnostic.stage}: {diagnostic.message}"
        )


@dataclass(frozen=True)
class V3InputFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class V3Game:
    game_id: str
    league_id: str
    boxscore: StatsNbaV3BoxscoreLoader
    pbp: StatsNbaV3PbpLoader
    classified: StatsNbaV3EventLoader
    lineups: StatsNbaV3LineupLoader
    possessions: StatsNbaV3PossessionLoader
    shot_zones: Optional[StatsNbaV3ShotZoneLoader]
    possession_start_types: Tuple[Optional[str], ...]
    diagnostics: Tuple[V3Diagnostic, ...]
    capabilities: Mapping[str, str]
    inputs: Mapping[str, V3InputFile]

    def __post_init__(self):
        object.__setattr__(
            self, "capabilities", MappingProxyType(dict(self.capabilities))
        )
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))


@contextmanager
def _stage(game_id, name):
    try:
        yield
    except (OSError, ValueError, TypeError) as error:
        code = (
            "missing_file" if isinstance(error, FileNotFoundError) else "invalid_input"
        )
        raise V3GameLoadError(game_id, V3Diagnostic(name, code, str(error))) from error


def _file(path, raw):
    return V3InputFile(str(path.resolve()), hashlib.sha256(raw).hexdigest())


def _path(directory, supplied, default=None):
    path = Path(default if supplied is None else supplied)
    return path if path.is_absolute() else directory / path


def _load_inputs(
    game_id,
    data_directory,
    league_id,
    snapshot_complete,
    jump_ball_evidence=None,
    jump_ball_live=None,
):
    with _stage(game_id, "configuration"):
        rules = V3LeagueRules.for_game(game_id, league_id)
        validate_file_directory(data_directory)
        if snapshot_complete is not True:
            raise ValueError(
                "snapshot_complete=True requires an explicit complete-PBP declaration"
            )
        directory = Path(data_directory)
        if (jump_ball_evidence is None) != (jump_ball_live is None):
            raise ValueError(
                "jump_ball_evidence and jump_ball_live must be supplied together"
            )
    with _stage(game_id, "boxscore"):
        source = StatsNbaV3BoxscoreFileLoader(
            directory, league_id=rules.league_id
        ).load_data(game_id)
        # Canonical labels bind evidence to the bundle, not the machine's path.
        prefix = f"game_details/stats_v3_boxscore_{game_id}"
        source = source._replace(
            boxscore_source=prefix + ".json", evidence_source=prefix + ".evidence.json"
        )
        box = StatsNbaV3BoxscoreLoader(
            game_id,
            SimpleNamespace(load_data=lambda _: source),
            league_id=rules.league_id,
        )
        box.require_complete_roster()
    with _stage(game_id, "pbp"):
        raw = StatsNbaV3PbpLoader(
            game_id,
            StatsNbaV3PbpFileLoader(directory, league_id=rules.league_id),
            league_id=rules.league_id,
        )
    jumps = None
    if jump_ball_evidence is not None:
        with _stage(game_id, "jump_balls"):
            jumps = V3JumpBallEvidence.from_files(
                _path(directory, jump_ball_evidence), _path(directory, jump_ball_live)
            )
    with _stage(game_id, "participants"):
        participants = StatsNbaV3ParticipantLoader(
            raw, box.context, snapshot_complete=True, jump_ball_evidence=jumps
        )
    with _stage(game_id, "classification"):
        classified = StatsNbaV3EventLoader(participants)
        if (
            not classified.items
            or max(e.group.primary.period for e in classified.items) < 4
        ):
            raise ValueError("a complete game requires all four regulation periods")
    inputs = {
        "boxscore": _file(directory / source.boxscore_source, source.boxscore_bytes),
        "boxscore_evidence": _file(
            directory / source.evidence_source, source.evidence_bytes
        ),
        "pbp": _file(directory / "pbp" / f"stats_v3_{game_id}.json", raw.source_bytes),
    }
    if jumps is not None:
        inputs["jump_ball_evidence"] = _file(
            _path(directory, jump_ball_evidence), jumps.review_bytes
        )
        inputs["jump_ball_live"] = _file(
            _path(directory, jump_ball_live), jumps.live_bytes
        )
    return directory, box, raw, classified, inputs


def load_game(
    game_id,
    data_directory,
    *,
    league_id=None,
    lineup_evidence=None,
    snapshot_complete=False,
    shot_evidence=None,
    jump_ball_evidence=None,
    jump_ball_live=None,
):
    """Load validated possessions from recorded files without network or writes.

    Evidence paths are absolute or relative to ``data_directory``. Lineups
    default to ``lineups.evidence.json``; live shot evidence is optional.
    Blank team-recovery jumps require both ``jump_ball_evidence`` (review)
    and ``jump_ball_live`` (original live bytes); neither is auto-discovered.
    Complete PBP coverage must be explicitly declared. Required failures raise
    V3GameLoadError with a stage and cause. Unresolved optional labels return
    None plus diagnostics, while the underlying strict event accessors remain.
    """
    directory, box, raw, classified, inputs = _load_inputs(
        game_id,
        data_directory,
        league_id,
        snapshot_complete,
        jump_ball_evidence,
        jump_ball_live,
    )
    with _stage(game_id, "lineups"):
        path = _path(directory, lineup_evidence, "lineups.evidence.json")
        evidence = V3LineupEvidence.from_file(path)
        lineups = StatsNbaV3LineupLoader(classified, evidence)
        inputs["lineups"] = _file(path, evidence.source_bytes)
    zones = None
    if shot_evidence is not None:
        with _stage(game_id, "shot_zones"):
            path = _path(directory, shot_evidence)
            source = V3LiveShotEvidence.from_file(path)
            zones = StatsNbaV3ShotZoneLoader(classified, source)
            inputs["shot_zones"] = _file(path, source.source_bytes)
    with _stage(game_id, "possessions"):
        possessions = StatsNbaV3PossessionLoader(lineups, shot_zones=zones)
    diagnostics = [
        V3Diagnostic(
            "event_stats",
            "unavailable",
            "Detailed V3 event statistics are unavailable; use possessions.base_stats.",
        )
    ]
    if zones is not None:
        diagnostics.extend(
            V3Diagnostic(
                "shot_zones", "unresolved_zone", "; ".join(r.issues), (r.source_index,)
            )
            for r in zones.items
            if r.issues
        )
    labels = []
    for index, possession in enumerate(possessions.items):
        try:
            labels.append(possession.possession_start_type)
        except ValueError as error:
            labels.append(None)
            diagnostics.append(
                V3Diagnostic(
                    "possession_start_types",
                    "unavailable_label",
                    str(error),
                    possession_index=index,
                )
            )
    capabilities = dict(
        possessions="complete",
        lineups="complete",
        base_stats="complete",
        detailed_event_stats="unavailable",
        possession_start_types="partial" if None in labels else "complete",
        shot_zone_evidence="not_supplied"
        if zones is None
        else "partial"
        if any(r.issues for r in zones.items)
        else "complete",
    )
    return V3Game(
        game_id,
        box.context.league_id,
        box,
        raw,
        classified,
        lineups,
        possessions,
        zones,
        tuple(labels),
        tuple(diagnostics),
        capabilities,
        inputs,
    )
