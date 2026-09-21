"""Import previously captured native responses without altering their bytes."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from pbpstats.data_loader.stats_nba_v3.boxscore import (
    StatsNbaV3BoxscoreLoader,
    V3BoxscoreSourceData,
)
from pbpstats.data_loader.stats_nba_v3.context import _name_key
from pbpstats.data_loader.stats_nba_v3.game import _stage
from pbpstats.data_loader.stats_nba_v3.pbp import StatsNbaV3PbpLoader
from pbpstats.data_loader.stats_nba_v3.pbp.file import (
    _finite_float,
    _reject_constant,
    _unique_object,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData
from pbpstats.resources.league_rules import V3LeagueRules


def _json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} requires nonempty source evidence")
    return value


def _box(game_id, raw, sidecar):
    prefix = f"game_details/stats_v3_boxscore_{game_id}"
    source = V3BoxscoreSourceData(
        raw, _json_bytes(sidecar), prefix + ".json", prefix + ".evidence.json"
    )
    return StatsNbaV3BoxscoreLoader(
        game_id, SimpleNamespace(load_data=lambda _: source)
    )


def _explicit_aliases(box, pbp, origin):
    aliases = []
    digest = hashlib.sha256(pbp.source_bytes).hexdigest()
    known = {
        p.player_id: {_name_key(n) for n in p.aliases} for p in box.context.players
    }
    for row in pbp.items:
        pid = row.get("personId")
        player = box.context.player(pid) if type(pid) is int else None
        if player is None:
            continue  # Outside-roster IDs need separate evidence, never roster additions.
        names = [row.get(k) for k in ("playerName", "playerNameI")]
        names = [n for n in names if isinstance(n, str) and n.strip()]
        if names and (
            type(row.get("teamId")) is not int or row.get("teamId") != player.team_id
        ):
            raise ValueError(
                f"source row {row.order}: alias player/team conflicts with box score"
            )
        new = []
        for name in names:
            if _name_key(name) not in known[pid]:
                known[pid].add(_name_key(name))
                new.append(name)
        if new:
            aliases.append(
                dict(
                    player_id=pid,
                    team_id=player.team_id,
                    names=new,
                    source=f"{origin}; explicit personId/teamId and playerName/playerNameI at source row {row.order}; PBP sha256={digest}",
                )
            )
    return aliases


def import_recordings(
    game_id,
    destination,
    *,
    pbp_file,
    boxscore_file,
    pbp_source,
    boxscore_source,
    league_id=None,
    roster_complete=False,
    completeness_basis="",
    aliases=(),
    bench_people=(),
):
    """Validate and copy recordings into a NEW bundle directory, offline.

    Origins and roster completeness are caller assertions. The import time
    is not represented as the original retrieval time. Names may be added
    only from explicit ID/team-bound name fields or supplied alias evidence.
    This operation does not certify PBP completeness, starters or batches.
    """
    with _stage(game_id, "import"):
        rules = V3LeagueRules.for_game(game_id, league_id)
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(f"bundle already exists: {destination}")
        _text(pbp_source, "pbp_source")
        _text(boxscore_source, "boxscore_source")
        if type(roster_complete) is not bool:
            raise ValueError("roster_complete must be a boolean")
        if roster_complete:
            _text(completeness_basis, "completeness_basis")
        pbp_raw, box_raw = Path(pbp_file).read_bytes(), Path(boxscore_file).read_bytes()
        try:
            payload = json.loads(
                pbp_raw.decode("utf-8-sig"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            )
        except RecursionError as error:
            raise ValueError("PBP recording exceeds supported JSON nesting") from error
        pbp = StatsNbaV3PbpLoader(
            game_id,
            SimpleNamespace(load_data=lambda _: V3PbpSourceData(payload, pbp_raw)),
            league_id=rules.league_id,
        )
        sidecar = dict(
            schema_version=1,
            game_id=game_id,
            boxscore_sha256=hashlib.sha256(box_raw).hexdigest(),
            source=boxscore_source,
            scope="full_game" if roster_complete else "unknown",
            roster_complete=roster_complete,
            completeness_basis=completeness_basis,
            aliases=list(aliases),
            bench_people=list(bench_people),
        )
        box = _box(game_id, box_raw, sidecar)
        sidecar["aliases"].extend(_explicit_aliases(box, pbp, pbp_source))
        box = _box(
            game_id, box_raw, sidecar
        )  # Validate generated and supplied evidence together.
        files = {
            f"pbp/stats_v3_{game_id}.json": (pbp_raw, pbp_source),
            f"game_details/stats_v3_boxscore_{game_id}.json": (
                box_raw,
                boxscore_source,
            ),
            f"game_details/stats_v3_boxscore_{game_id}.evidence.json": (
                box.source.evidence_bytes,
                "Generated roster assertions and explicit-ID aliases",
            ),
        }
        manifest = dict(
            schema_version=1,
            game_id=game_id,
            league_id=rules.league_id,
            imported_at_utc=datetime.now(timezone.utc).isoformat(),
            method="Local recording import; original bytes preserved; origins are caller assertions",
            files=[
                dict(path=name, sha256=hashlib.sha256(raw).hexdigest(), source=source)
                for name, (raw, source) in files.items()
            ],
        )
        # All validation precedes creation; exclusive writes never replace an existing bundle.
        destination.mkdir(parents=True, exist_ok=False)
        for name, (raw, _) in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
        with (destination / "manifest.json").open("xb") as stream:
            stream.write(_json_bytes(manifest))
    return destination
