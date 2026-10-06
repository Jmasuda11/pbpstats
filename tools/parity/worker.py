"""One parser per process. Output JSON only; all network access is disabled."""

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile


def offline(*args, **kwargs):
    raise RuntimeError("Parity worker attempted network access")


def seeded_v2(events):
    from tools.parity.scenarios import encode_v2

    return seeded_v2_rows(encode_v2(events))


def seeded_v2_rows(rows, coordinates=None):
    from tools.parity.scenarios import HOME, AWAY, GAME
    from pbpstats.data_loader.nba_enhanced_pbp_loader import NbaEnhancedPbpLoader
    from pbpstats.data_loader.nba_possession_loader import NbaPossessionLoader
    from pbpstats.resources.enhanced_pbp.stats_nba.enhanced_pbp_factory import (
        StatsNbaEnhancedPbpFactory,
    )
    from pbpstats.resources.possessions.possession import Possession

    class Seeded(NbaEnhancedPbpLoader, NbaPossessionLoader):
        game_id = GAME
        league = "nba"
        file_directory = None

        def _set_period_start_items(self):
            # Independent synthetic starter evidence, not inference from V3.
            for index in self.start_period_indices:
                start = self.items[index]
                start.period_starters = {
                    HOME: [1, 2, 3, 4, 5],
                    AWAY: [11, 12, 13, 14, 15],
                }
                start.team_starting_with_ball = start.get_team_starting_with_ball()

    loaded = Seeded()
    factory = StatsNbaEnhancedPbpFactory()
    loaded.items = [
        factory.get_event_class(row["EVENTMSGTYPE"])(row, index)
        for index, row in enumerate(rows)
    ]
    for event in loaded.items:
        if coordinates and event.event_num in coordinates:
            event.locX, event.locY = coordinates[event.event_num]
    loaded._add_extra_attrs_to_all_events()
    loaded.events = loaded.items
    loaded.items = [Possession(group) for group in loaded._split_events_by_possession()]
    loaded._add_extra_attrs_to_all_possessions()
    return loaded


def prior_v3(events, package):
    from types import SimpleNamespace
    from tools.parity.scenarios import GAME, encode_v3

    sys.path.insert(1, str(package / "tests"))
    sys.path.insert(1, str(package / "tests/data_loaders"))
    import test_stats_v3_lineups as fixture
    from pbpstats.data_loader.stats_nba_v3.pbp import StatsNbaV3PbpLoader
    from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData
    from pbpstats.data_loader.stats_nba_v3.participants import (
        StatsNbaV3ParticipantLoader,
    )
    from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
    from pbpstats.data_loader.stats_nba_v3.lineups import (
        StatsNbaV3LineupLoader,
        V3LineupEvidence,
    )
    from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader

    rows = encode_v3(events)
    raw = StatsNbaV3PbpLoader(
        GAME,
        SimpleNamespace(
            load_data=lambda _: V3PbpSourceData(
                {"game": {"gameId": GAME, "actions": rows}}
            )
        ),
    )
    facts = StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(raw, fixture.context(), snapshot_complete=True)
    )
    evidence = fixture.evidence(
        facts, batches=[[i] for i, event in enumerate(events) if event["kind"] == "sub"]
    )
    lineups = StatsNbaV3LineupLoader(
        facts,
        V3LineupEvidence(json.dumps(evidence).encode(), "independent-synthetic"),
        use_v2_rules=True,
    )
    return StatsNbaV3PossessionLoader(lineups)


def prior_recorded(package):
    sys.path.insert(1, str(package / "tests"))
    from v3_context_fixture import DATA, recorded_boxscore
    from pbpstats.data_loader.stats_nba_v3.pbp import (
        StatsNbaV3PbpFileLoader,
        StatsNbaV3PbpLoader,
    )
    from pbpstats.data_loader.stats_nba_v3.participants import (
        StatsNbaV3ParticipantLoader,
    )
    from pbpstats.data_loader.stats_nba_v3.classification import StatsNbaV3EventLoader
    from pbpstats.data_loader.stats_nba_v3.lineups import (
        StatsNbaV3LineupLoader,
        V3LineupEvidence,
    )
    from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader

    context = recorded_boxscore().context
    raw = StatsNbaV3PbpLoader(context.game_id, StatsNbaV3PbpFileLoader(DATA))
    facts = StatsNbaV3EventLoader(
        StatsNbaV3ParticipantLoader(raw, context, snapshot_complete=True)
    )
    return StatsNbaV3PossessionLoader(
        StatsNbaV3LineupLoader(
            facts,
            V3LineupEvidence.from_file(DATA / "v3/lineups_0021900001.evidence.json"),
            use_v2_rules=True,
        )
    )


def credit_snapshot(loaded):
    from tools.parity.snapshot import scalar

    groups = []
    for possession in loaded.items:
        end = possession.events[-1]
        credits = sorted(
            [
                row["team_id"],
                row["player_id"],
                row["stat_key"],
                row["lineup_id"],
                row["opponent_lineup_id"],
            ]
            for row in end.base_stats
            if row["stat_key"] in ("OffPoss", "DefPoss")
        )
        groups.append(
            dict(
                period=possession.period,
                end=end.event_num,
                offense=possession.offense_team_id,
                counted=bool(end.count_as_possession),
                credits=credits,
            )
        )
    last = loaded.events[-1]
    return scalar(
        dict(
            groups=groups,
            score={team: last.score.get(team, 0) for team in last.current_players},
            events=len(loaded.events),
        )
    )


def result_for(name, callback, source, snapshotter=None):
    from tools.parity.snapshot import snapshot

    try:
        loaded = callback()
        return dict(
            name=name,
            status="ok",
            source=source,
            credits=credit_snapshot(loaded),
            snapshot=(snapshotter or snapshot)(loaded),
        )
    except Exception as error:
        return dict(
            name=name,
            status="error",
            source=source,
            error=type(error).__name__ + ": " + str(error),
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--provider", choices=("v2", "prior_v3", "v3"), default="v2")
    parser.add_argument(
        "--suite",
        choices=(
            "synthetic",
            "archived",
            "paired",
            "shots",
            "participants",
            "free-throws",
            "exceptions",
            "team-heaves",
        ),
        default="synthetic",
    )
    parser.add_argument("--fixtures", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    sys.dont_write_bytecode = True
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    socket.create_connection = offline
    sys.path.insert(0, str(package))
    import pbpstats

    imported = Path(pbpstats.__file__).resolve()
    if imported != package / "pbpstats/__init__.py":
        raise RuntimeError("Wrong parser imported: " + str(imported))
    sys.path.insert(1, str(Path(__file__).resolve().parents[2]))
    from tools.parity.scenarios import catalog, encode_v2, encode_v3
    from tools.parity.reference import digest

    if args.suite == "exceptions":
        from tools.parity.exception_cases import run_cases

        results = run_cases(args.provider)
    elif args.suite == "team-heaves":
        from tools.parity import team_heave_cases

        if args.provider not in ("v2", "v3"):
            raise ValueError("Team heave analogues support original V2 and candidate V3")
        results = []
        for case in team_heave_cases.catalog():
            rows = (team_heave_cases.v2_inputs if args.provider == "v2"
                    else team_heave_cases.v3_inputs)(case)
            callback = (lambda rows=rows: seeded_v2_rows(rows)) if args.provider == "v2" else (
                lambda rows=rows: team_heave_cases.load_v3(rows)
            )
            results.append(result_for(
                case["name"], callback,
                dict(kind="controlled-team-miss-analogue-not-historical-V2-parity",
                     rows=rows, sha256=digest(json.dumps(rows, sort_keys=True).encode())),
                snapshotter=team_heave_cases.behavior_snapshot,
            ))
    elif args.suite == "shots":
        from tools.parity.shot_cases import (
            catalog as shot_catalog,
            v2_inputs,
            v3_inputs,
            shot_snapshot,
        )

        if args.provider not in ("v2", "v3"):
            raise ValueError(
                "Shot evidence suite supports original V2 and candidate V3"
            )
        results = []
        for case in shot_catalog():
            if args.provider == "v2":
                rows, coordinates = v2_inputs(case)
                callback = lambda rows=rows, coordinates=coordinates: seeded_v2_rows(
                    rows, coordinates
                )
            else:
                from tools.parity.v3_cases import load_synthetic_rows

                rows = v3_inputs(case)
                coordinates = None
                callback = lambda rows=rows: load_synthetic_rows(rows)
            results.append(
                result_for(
                    case["name"],
                    callback,
                    {
                        "kind": "independently-encoded-shot-facts",
                        "rows": rows,
                        "coordinates": coordinates,
                        "sha256": digest(
                            json.dumps(
                                {"rows": rows, "coordinates": coordinates},
                                sort_keys=True,
                            ).encode()
                        ),
                        "vocabulary_sha256": digest(
                            (
                                Path(__file__).resolve().parents[2]
                                / "tests/parity/shot-vocabulary.json"
                            ).read_bytes()
                        ),
                    },
                    snapshotter=shot_snapshot,
                )
            )
    elif args.suite == "free-throws":
        from tools.parity import free_throw_cases

        if args.provider not in ("v2", "v3"):
            raise ValueError("Free throw suite supports original V2 and candidate V3")
        results = []
        for case in free_throw_cases.catalog():
            if args.provider == "v2":
                rows, coordinates = free_throw_cases.v2_inputs(case)
                callback = lambda rows=rows, coordinates=coordinates: seeded_v2_rows(
                    rows, coordinates
                )
            else:
                from tools.parity.v3_cases import load_synthetic_rows

                rows, coordinates = free_throw_cases.v3_inputs(case), None
                callback = lambda rows=rows: load_synthetic_rows(rows)
            facts = dict(rows=rows, coordinates=coordinates)
            results.append(
                result_for(
                    case["name"],
                    callback,
                    dict(
                        kind="independently-verified-flagrant-free-throws",
                        facts=facts,
                        sha256=digest(json.dumps(facts, sort_keys=True).encode()),
                    ),
                    snapshotter=free_throw_cases.free_throw_snapshot,
                )
            )
    elif args.suite == "participants":
        from tools.parity import participant_cases
        from tools.parity.shot_cases import shot_snapshot

        if args.provider not in ("v2", "v3"):
            raise ValueError("Participant suite supports original V2 and candidate V3")
        results = []
        for case in participant_cases.catalog():
            if args.provider == "v2":
                rows, coordinates = participant_cases.v2_inputs(case)
                callback = lambda rows=rows, coordinates=coordinates: seeded_v2_rows(
                    rows, coordinates
                )
                facts = dict(rows=rows, coordinates=coordinates)
            else:
                rows, roster = participant_cases.v3_inputs(case)
                callback = lambda rows=rows, roster=roster: participant_cases.load_v3(
                    rows, roster
                )
                facts = dict(rows=rows, roster=roster)
            results.append(
                result_for(
                    case["name"],
                    callback,
                    dict(
                        kind="independently-encoded-participant-facts",
                        facts=facts,
                        sha256=digest(json.dumps(facts, sort_keys=True).encode()),
                    ),
                    snapshotter=shot_snapshot,
                )
            )
    elif args.suite == "synthetic":
        results = []
        for case in catalog():
            rows = (encode_v2 if args.provider == "v2" else encode_v3)(case["events"])
            if args.provider == "v2":
                callback = lambda case=case: seeded_v2(case["events"])
            elif args.provider == "prior_v3":
                callback = lambda case=case: prior_v3(case["events"], package)
            else:
                from tools.parity.v3_cases import load_synthetic

                callback = lambda case=case: load_synthetic(case["events"])
            results.append(
                result_for(
                    case["name"],
                    callback,
                    {
                        "rows": rows,
                        "sha256": digest(json.dumps(rows, sort_keys=True).encode()),
                        "kind": "independently-encoded-synthetic",
                    },
                )
            )
    elif args.suite == "paired" and args.provider == "prior_v3":
        data = package / "tests/data/pbp/stats_v3_0021900001.json"
        results = [
            result_for(
                "0021900001",
                lambda: prior_recorded(package),
                {"kind": "archived-v3", "sha256": digest(data.read_bytes())},
            )
        ]
    elif args.suite == "paired" and args.provider == "v3":
        from tools.parity.v3_cases import load_paired

        data = args.fixtures / "pbp/stats_v3_0021900001.json"
        results = [
            result_for(
                "0021900001",
                lambda: load_paired(args.fixtures),
                {"kind": "archived-v3", "sha256": digest(data.read_bytes())},
            )
        ]
    else:
        from pbpstats.data_loader.stats_nba.possessions.file import (
            StatsNbaPossessionFileLoader,
        )
        from pbpstats.data_loader.stats_nba.possessions.loader import (
            StatsNbaPossessionLoader,
        )

        if args.provider != "v2" or args.fixtures is None:
            raise ValueError("Archived suite requires V2 and explicit fixtures")
        results = []
        # Original loaders can repair/write cached files; run on temporary copies.
        with tempfile.TemporaryDirectory(prefix="pbpstats-parity-") as folder:
            data = Path(folder) / "data"
            shutil.copytree(args.fixtures, data)
            game_ids = (
                ("0021900001",)
                if args.suite == "paired"
                else ("0021900001", "0021600270", "2021900002")
            )
            for game_id in game_ids:
                results.append(
                    result_for(
                        game_id,
                        lambda game_id=game_id: StatsNbaPossessionLoader(
                            game_id, StatsNbaPossessionFileLoader(str(data))
                        ),
                        {
                            "kind": "archived-v2",
                            "sha256": digest(
                                (
                                    args.fixtures
                                    / "pbp"
                                    / ("stats_" + game_id + ".json")
                                ).read_bytes()
                            ),
                        },
                    )
                )
    source_hashes = {
        path.relative_to(package).as_posix(): digest(path.read_bytes())
        for path in sorted((package / "pbpstats").rglob("*.py"))
    }
    print(
        json.dumps(
            dict(
                package=str(imported),
                source_hashes=source_hashes,
                provider=args.provider,
                suite=args.suite,
                statuses=dict(Counter(r["status"] for r in results)),
                results=results,
            )
        )
    )


if __name__ == "__main__":
    main()
