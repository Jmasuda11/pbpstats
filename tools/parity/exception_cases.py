"""Independent failure/recovery fixtures; no rejected game counts as a success.

Full-loader cases run the original file loader, including starter overrides,
source repairs and alternation validation. Property cases name their narrower
boundary explicitly. All files are temporary; production recordings are inputs.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from tools.parity.scenarios import AWAY, HOME, GAME, e, encode_v2, encode_v3, wrap


BAD = "bad_pbp_possessions.json"
CHANGE = "possession_change_event_overrides.json"
KEEP = "non_possession_changing_event_overrides.json"
STARTERS = {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}
ALTERNATION = "TeamHasBackToBackPossessionsException"


def catalog():
    cases = []

    def add(name, plays, exception=None, **kw):
        # Give original starter inference independent witnesses for both teams;
        # its normal missing-period-starters file supplies the remaining players.
        events = wrap(
            [
                e("foul", 710, HOME, 2, subtype="Personal"),
                e("foul", 700, AWAY, 12, subtype="Personal"),
            ]
            + plays
        )
        cases.append(
            dict(
                name=name,
                events=events,
                boundary="loader",
                expected_exception=exception,
                overrides={},
                **kw,
            )
        )

    add("alternating_possessions", [e("make"), e("make", 580, AWAY, 11)])
    repeated = [e("make"), e("make", 580)]
    add("back_to_back_scores", repeated, ALTERNATION)
    add("back_to_back_turnovers", [e("turnover"), e("turnover", 580)], ALTERNATION)
    add("bad_possession_override", repeated)
    cases[-1]["overrides"] = {BAD: {GAME: {1: [2]}}}
    for name, values in (
        ("wrong_game", {"0021900002": {1: [2]}}),
        ("wrong_period", {GAME: {2: [2]}}),
        ("wrong_number", {GAME: {1: [1]}}),
    ):
        add("bad_possession_override_" + name, repeated, ALTERNATION)
        cases[-1]["overrides"] = {BAD: values}
    add("override_does_not_hide_next_failure", repeated + [e("make", 560)], ALTERNATION)
    cases[-1]["overrides"] = {BAD: {GAME: {1: [2]}}}
    add(
        "flagrant_exempts_adjacent_repeat",
        [e("foul", 610, AWAY, 11, subtype="Flagrant Type 1"), *repeated],
    )
    add(
        "ordinary_foul_does_not_exempt_repeat",
        [e("foul", 610, AWAY, 11, subtype="Personal"), *repeated],
        ALTERNATION,
    )
    add(
        "flagrant_two_possessions_back",
        [
            e("foul", 620, AWAY, 11, subtype="Flagrant Type 1"),
            e("make", 610),
            e("make", 600, AWAY, 11),
            e("make", 580, AWAY, 11),
        ],
    )
    add(
        "flagrant_exemption_expires",
        [
            e("foul", 630, AWAY, 11, subtype="Flagrant Type 1"),
            e("make", 620),
            e("make", 610, AWAY, 11),
            e("make", 600),
            e("make", 580),
        ],
        ALTERNATION,
    )

    add("suppress_score_boundary", repeated)
    cases[-1]["overrides"] = {KEEP: {GAME: [4]}}
    add("force_timeout_boundary", [e("timeout", 610, 0, 0), e("make")], ALTERNATION)
    cases[-1]["overrides"] = {CHANGE: {GAME: [4]}}
    add(
        "force_boundary_with_specific_exception_override",
        [e("timeout", 610, 0, 0), e("make")],
    )
    cases[-1]["overrides"] = {CHANGE: {GAME: [4]}, BAD: {GAME: {1: [2]}}}
    add("unrelated_event_override", repeated, ALTERNATION)
    cases[-1]["overrides"] = {KEEP: {"0021900002": [4]}}
    add("zero_event_number_override", [e("make"), e("make", 580, AWAY, 11)])
    cases[-1]["overrides"] = {KEEP: {GAME: [0]}}
    add("numeric_string_override_values", repeated)
    cases[-1]["overrides"] = {BAD: {GAME: {"1": ["2"]}}}

    add(
        "repair_replay_between_miss_and_rebound",
        [
            e("miss"),
            e("replay", 599, 0, 0),
            e("rebound", 598, AWAY, 11),
            e("make", 580, AWAY, 11),
        ],
    )
    add(
        "repair_timeout_between_missed_ft_and_rebound",
        [
            e("foul", 610, AWAY, 11, subtype="Shooting"),
            e("ft", 610, attempt=1, total=2, made=True),
            e("ft", 610, attempt=2, total=2, made=False),
            e("timeout", 610, 0, 0),
            e("rebound", 609, AWAY, 11),
            e("make", 580, AWAY, 11),
        ],
    )
    add(
        "repair_substitution_between_missed_ft_and_rebound",
        [
            e("foul", 610, AWAY, 11, subtype="Shooting"),
            e("ft", 610, attempt=1, total=2, made=True),
            e("ft", 610, attempt=2, total=2, made=False),
            e("sub", 610, HOME, 2, incoming=6),
            e("rebound", 609, AWAY, 11),
            e("make", 580, AWAY, 11),
        ],
    )
    add("repair_technical_before_start", [e("make"), e("make", 580, AWAY, 11)])
    cases[-1]["events"] = [
        e("foul", 720, AWAY, 11, subtype="Technical"),
        e("ft", 720, HOME, 1, category="Technical", attempt=1, total=1, made=True),
    ] + cases[-1]["events"]

    add(
        "repair_rebound_and_next_shot_reversed",
        [e("miss"), e("rebound", 599, AWAY, 11), e("make", 580, AWAY, 11)],
    )
    cases[-1]["source_order"] = [1, 2, 3, 4, 6, 5, 7]
    for name, order in (
        ("repair_first_rebound_before_second_miss", [1, 2, 3, 4, 6, 5, 7, 8, 9]),
        ("repair_second_rebound_before_second_miss", [1, 2, 3, 4, 6, 7, 5, 8, 9]),
    ):
        add(
            name,
            [
                e("miss", 620),
                e("rebound", 619),
                e("miss", 610),
                e("rebound", 609, AWAY, 11),
                e("make", 580, AWAY, 11),
            ],
        )
        cases[-1]["source_order"] = order
    fallback = [
        e("miss", 610),
        e("foul", 610, HOME, 2, subtype="Personal"),
        e("rebound", 609, AWAY, 11),
        e("make", 580, AWAY, 11),
    ]
    add("recorded_provider_order_recovers_rebound", fallback)
    cases[-1]["provider_order"] = [1, 2, 3, 5, 4, 6, 7, 8]
    add("provider_extra_events_do_not_change_matching_order", fallback)
    cases[-1]["provider_order"] = [0, 1, 2, 3, 5, 4, 6, 7, 8, 999]
    add("provider_order_still_invalid", fallback, "EventOrderError")
    cases[-1]["provider_order"] = list(range(1, 9))

    for name, plays, exception in (
        (
            "rebound_after_make",
            [e("make"), e("rebound", 599, AWAY, 11)],
            "EventOrderError",
        ),
        ("rebound_after_miss", [e("miss"), e("rebound", 599, AWAY, 11)], None),
        (
            "rebound_after_turnover",
            [e("turnover"), e("rebound", 599, AWAY, 11)],
            "EventOrderError",
        ),
    ):
        add(name, plays, exception)
        cases[-1]["boundary"] = "rebound_property"
    add(
        "insufficient_inferred_starters",
        [e("make"), e("make", 580, AWAY, 11)],
        "InvalidNumberOfStartersException",
    )
    cases[-1]["boundary"] = "starter_inference"
    add("starter_override_recovers_inference", [e("make"), e("make", 580, AWAY, 11)])
    cases[-1].update(boundary="starter_inference", starter_override=True)
    for name, supplied in (
        ("starter_override_file_missing", None),
        ("starter_override_wrong_game", {"0021900002": {1: STARTERS}}),
        ("starter_override_wrong_period", {GAME: {2: STARTERS}}),
        ("starter_override_wrong_team", {GAME: {1: {AWAY: STARTERS[AWAY]}}}),
    ):
        add(
            name,
            [e("make"), e("make", 580, AWAY, 11)],
            "InvalidNumberOfStartersException",
        )
        cases[-1].update(boundary="starter_inference", starter_directory=supplied)
    add(
        "too_many_inferred_starters",
        [e("foul", 690 - p, HOME, p, subtype="Personal") for p in (1, 3, 4, 5, 6)]
        + [e("make")],
        "InvalidNumberOfStartersException",
    )
    cases[-1]["boundary"] = "starter_inference"
    for name, teams, exception in (
        (
            "boxscore_fewer_than_ten_players",
            [HOME] * 5 + [AWAY] * 4,
            "InvalidNumberOfStartersException",
        ),
        (
            "boxscore_unbalanced_teams",
            [HOME] * 6 + [AWAY] * 4,
            "InvalidNumberOfStartersException",
        ),
        ("boxscore_recovers_starters", [HOME] * 5 + [AWAY] * 5, None),
    ):
        add(name, [e("make"), e("make", 580, AWAY, 11)], exception)
        cases[-1].update(boundary="starter_boxscore", boxscore_teams=teams)
    from tools.parity.starter_cases import catalog as starter_catalog

    return cases + starter_catalog()


def result_set(rows, headers=None):
    headers = headers or list(dict.fromkeys(k for row in rows for k in row))
    return {
        "resultSets": [
            {
                "headers": headers,
                "rowSet": [[row.get(k) for k in headers] for row in rows],
            }
        ]
    }


def source_order(case, rows):
    return (
        [rows[n - 1] for n in case["source_order"]] if "source_order" in case else rows
    )


def v3_inputs(case):
    from pbpstats.data_loader.stats_nba_v3 import V3Context

    rows = source_order(case, encode_v3(case["events"]))
    # Equivalent literal descriptions make exception diagnostics comparable.
    # These are fixture literals, not fields decoded from the V2 parser.
    for row in rows:
        if row["actionType"] == "Rebound":
            row["description"] = "REBOUND"
        if row["actionType"] in ("Made Shot", "Missed Shot"):
            row.update(xLegacy=0, yLegacy=100)
        if row["actionType"] == "Free Throw":
            row["description"] = row["description"].replace(" (1 PTS)", "")
    raw = json.dumps({"game": {"gameId": GAME, "actions": rows}}).encode()
    context = V3Context(
        GAME,
        (HOME, AWAY),
        {
            p: dict(team_id=t, names=["Player{}".format(p)])
            for t, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
            for p in players
        },
        {1: deepcopy(STARTERS)},
        "Independent exception fixture",
        hashlib.sha256(raw).hexdigest(),
    )
    return raw, context


def override_bytes(case):
    return {
        name: json.dumps(values).encode() for name, values in case["overrides"].items()
    }


def original_loader(case, folder):
    from pbpstats.data_loader.stats_nba.possessions.file import (
        StatsNbaPossessionFileLoader,
    )
    from pbpstats.data_loader.stats_nba.possessions.loader import (
        StatsNbaPossessionLoader,
    )

    rows = source_order(case, encode_v2(case["events"]))
    for directory in ("pbp", "game_details", "overrides"):
        (folder / directory).mkdir(exist_ok=True)
    (folder / "pbp" / ("stats_" + GAME + ".json")).write_text(
        json.dumps(result_set(rows))
    )
    for side, team in (("home", HOME), ("away", AWAY)):
        shots = [
            dict(GAME_EVENT_ID=r["EVENTNUM"], LOC_X=0, LOC_Y=100)
            for r in rows
            if r["EVENTMSGTYPE"] in (1, 2) and r["PLAYER1_TEAM_ID"] == team
        ]
        (
            folder / "game_details" / ("stats_" + side + "_shots_" + GAME + ".json")
        ).write_text(json.dumps(result_set(shots, ["GAME_EVENT_ID", "LOC_X", "LOC_Y"])))
    (folder / "overrides/missing_period_starters.json").write_text(
        json.dumps({GAME: {1: STARTERS}})
    )
    for name, raw in override_bytes(case).items():
        (folder / "overrides" / name).write_bytes(raw)
    if "provider_order" in case:
        from pbpstats.data_loader.data_nba.pbp.web import DataNbaPbpWebLoader

        # Replace only the transport in the isolated oracle process. Its loader,
        # repair retries, provider-order algorithm and checks run unmodified.
        def recorded(loader, game_id):
            assert game_id == GAME
            return provider_payload(case)

        with patch.object(DataNbaPbpWebLoader, "load_data", recorded):
            return StatsNbaPossessionLoader(
                GAME, StatsNbaPossessionFileLoader(str(folder))
            )
    return StatsNbaPossessionLoader(GAME, StatsNbaPossessionFileLoader(str(folder)))


def provider_payload(case):
    return {
        "g": {
            "gid": GAME,
            "pd": [{"p": 1, "pla": [{"evt": n} for n in case["provider_order"]]}],
        }
    }


def property_events(case, provider):
    from pbpstats.data_loader.nba_enhanced_pbp_loader import NbaEnhancedPbpLoader
    from pbpstats.resources.enhanced_pbp.stats_nba.enhanced_pbp_factory import (
        StatsNbaEnhancedPbpFactory,
    )

    class Seeded(NbaEnhancedPbpLoader):
        game_id, league, file_directory = GAME, "nba", None

        def _set_period_start_items(self):
            for index in self.start_period_indices:
                start = self.items[index]
                start.period_starters = deepcopy(STARTERS)
                start.team_starting_with_ball = start.get_team_starting_with_ball()

    if provider == "v3":
        from pbpstats.data_loader.stats_nba_v3.decoder import DecodedV3

        rows = DecodedV3(*v3_inputs(case)).projected
    else:
        rows = encode_v2(case["events"])
    loader = Seeded()
    factory = StatsNbaEnhancedPbpFactory()
    loader.items = [
        factory.get_event_class(r["EVENTMSGTYPE"])(r, i) for i, r in enumerate(rows)
    ]
    loader._add_extra_attrs_to_all_events()
    return loader.items


def observe(case, provider, folder):
    if case["boundary"] == "starter_loader":
        from tools.parity.starter_cases import observe as starter_observe

        return starter_observe(case, provider, folder)
    if case["boundary"] != "loader":
        events = property_events(case, provider)
        if case["boundary"] == "rebound_property":
            rebound = next(e for e in events if e.event_type == 4)
            return {"missed_shot": rebound.missed_shot.event_num}
        if case["boundary"] == "starter_boxscore":
            from types import SimpleNamespace

            response = result_set(
                [
                    dict(TEAM_ID=team, PLAYER_ID=i + 1, MIN="0:05")
                    for i, team in enumerate(case["boxscore_teams"])
                ]
            )
            requests = []

            def recorded(url, params, **kwargs):
                requests.append(dict(url=url, params=params))
                return SimpleNamespace(status_code=200, json=lambda: response)

            with patch(
                "pbpstats.resources.enhanced_pbp.start_of_period.requests.get", recorded
            ):
                starters = events[0]._get_starters_from_boxscore_request()
            return dict(starters=starters, requests=requests)
        directory = None
        if case.get("starter_override") or "starter_directory" in case:
            (folder / "overrides").mkdir()
            supplied = (
                {GAME: {1: STARTERS}}
                if case.get("starter_override")
                else case["starter_directory"]
            )
            if supplied is not None:
                (folder / "overrides/missing_period_starters.json").write_text(
                    json.dumps(supplied)
                )
            directory = str(folder)
        return {
            "starters": events[0]._get_period_starters_from_period_events(directory)
        }
    if provider == "v2":
        loaded = original_loader(case, folder)
    else:
        from pbpstats.data_loader.stats_nba_v3 import (
            StatsNbaV3PossessionLoader,
            V3Overrides,
            V3EventOrder,
        )

        raw, context = v3_inputs(case)
        overrides = V3Overrides(
            override_bytes(case), "Independent correction fixture", context.pbp_sha256
        )
        ordering = (
            V3EventOrder(
                json.dumps(provider_payload(case)).encode(),
                "Independent provider fixture",
                context.pbp_sha256,
            )
            if "provider_order" in case
            else None
        )
        loaded = StatsNbaV3PossessionLoader(
            raw, context, overrides=overrides, event_order=ordering
        )
        if (
            loaded.decoded.source_bytes != raw
            or loaded.decoded.raw_rows != json.loads(raw)["game"]["actions"]
        ):
            raise AssertionError("Repair mutated raw source")
        if sorted(i for e in loaded.events for i in e.v3_source_indices) != list(
            range(len(loaded.decoded.raw_rows))
        ):
            raise AssertionError("Repair lost or duplicated source rows")
    from tools.parity.worker import credit_snapshot

    return dict(
        credits=credit_snapshot(loaded),
        events=[
            dict(
                number=e.event_num,
                lineup=e.current_players,
                force=e.possession_changing_override,
                keep=e.non_possession_changing_override,
                previous=e.previous_event.event_num if e.previous_event else None,
                next=e.next_event.event_num if e.next_event else None,
                missed_shot=e.missed_shot.event_num if e.event_type == 4 else None,
            )
            for e in loaded.events
        ],
        possessions=[[e.event_num for e in p.events] for p in loaded.items],
    )


def run_cases(provider):
    if provider not in ("v2", "v3"):
        raise ValueError("Exception suite requires original V2 or candidate V3")
    results = []
    for case in catalog():
        with tempfile.TemporaryDirectory(prefix="pbpstats-exceptions-") as directory:
            try:
                value = observe(case, provider, Path(directory))
                outcome = dict(kind="return", value=value)
            except Exception as error:
                outcome = dict(
                    kind="exception",
                    type=type(error).__name__,
                    module=type(error).__module__,
                    message=str(error),
                )
                if case["boundary"] == "starter_loader":
                    chain, linked = [], error.__context__
                    while linked is not None:
                        chain.append(
                            dict(
                                type=type(linked).__name__,
                                module=type(linked).__module__,
                                message=str(linked),
                            )
                        )
                        linked = linked.__context__
                    outcome["context"] = chain
        results.append(
            dict(
                name=case["name"],
                boundary=case["boundary"],
                status="observed",
                expected_exception=case["expected_exception"],
                outcome=outcome,
                fixture_sha256=hashlib.sha256(
                    json.dumps(case, sort_keys=True).encode()
                ).hexdigest(),
            )
        )
    return results
