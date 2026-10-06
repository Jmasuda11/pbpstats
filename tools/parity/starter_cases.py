"""Full-constructor starter recovery against the original file-loading path."""

from copy import deepcopy
import json
from unittest.mock import patch

import requests

from tools.parity.scenarios import HOME, AWAY, GAME, e, wrap, encode_v2


STARTERS = {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}
FILE = "missing_period_starters.json"


def players():
    return [
        dict(TEAM_ID=team, PLAYER_ID=p, MIN="0:05")
        for team, ids in STARTERS.items()
        for p in ids
    ]


def catalog():
    cases = []
    sparse = wrap(
        [
            e("foul", 710, HOME, 2, subtype="Personal"),
            e("foul", 700, AWAY, 12, subtype="Personal"),
            e("make"),
            e("make", 580, AWAY, 11),
        ]
    )
    complete = wrap(
        [
            e("foul", 710 - i, team, p, subtype="Personal")
            for i, (team, p) in enumerate(
                (t, p) for t, ids in STARTERS.items() for p in ids
            )
        ]
        + [e("make"), e("make", 580, AWAY, 11)]
    )

    def add(name, events=None, exception=None, **extra):
        cases.append(
            dict(
                name="starter_loader_" + name,
                boundary="starter_loader",
                expected_exception=exception,
                events=deepcopy(events or sparse),
                overrides={},
                responses={},
                **extra,
            )
        )
        return cases[-1]

    def box(
        case,
        *,
        period=1,
        start=0,
        end=100,
        rows=None,
        status=200,
        reason="OK",
        raw=None,
    ):
        from tools.parity.exception_cases import result_set

        case["responses"][period] = dict(
            params=dict(
                GameId=GAME,
                StartPeriod=0,
                EndPeriod=0,
                RangeType=2,
                StartRange=start,
                EndRange=end,
            ),
            status=status,
            reason=reason,
            body=(
                raw
                if raw is not None
                else json.dumps(result_set(players() if rows is None else rows))
            ),
        )

    add("inference_without_io", complete)
    case = add("complete_inference_ignores_override_and_boxscore", complete)
    case["overrides"] = {FILE: {GAME: {1: {HOME: [1, 2, 3, 4, 6]}}}}
    box(case, status=500, reason="Server Error", raw="unused")
    case = add("override_recovers_without_boxscore")
    case["overrides"] = {FILE: {GAME: {1: STARTERS}}}
    box(case, status=500, reason="Server Error", raw="unused")
    box(add("boxscore_recovers_without_override"))
    for name, corrections in (
        ("wrong_game", {"0021900002": {1: STARTERS}}),
        ("wrong_period", {GAME: {2: STARTERS}}),
        ("wrong_team", {GAME: {1: {999: [1, 2, 3, 4, 5]}}}),
        ("partial_override", {GAME: {1: {HOME: [1, 2, 3, 4, 6]}}}),
    ):
        case = add(name + "_falls_back")
        case["overrides"] = {FILE: corrections}
        box(case)
    case = add(
        "too_many_inferred_players",
        wrap(
            [
                e("foul", 710 - i, HOME, p, subtype="Personal")
                for i, p in enumerate(range(1, 7))
            ]
            + [
                e("foul", 700, AWAY, 12, subtype="Personal"),
                e("make"),
                e("make", 580, AWAY, 11),
            ]
        ),
    )
    box(case)
    box(
        add("boxscore_nine_players", exception="InvalidNumberOfStartersException"),
        rows=players()[:-1],
    )
    unbalanced = players()
    unbalanced[5]["TEAM_ID"] = HOME
    box(
        add("boxscore_six_four", exception="InvalidNumberOfStartersException"),
        rows=unbalanced,
    )
    box(
        add("boxscore_seconds_component_sort"),
        rows=[dict(TEAM_ID=HOME, PLAYER_ID=6, MIN="1:01")] + players(),
    )
    box(add("boxscore_tie_order"), rows=list(reversed(players())))
    box(
        add("boxscore_ignores_extra_low_seconds"),
        rows=players()
        + [
            dict(TEAM_ID=HOME, PLAYER_ID=6, MIN="0:00"),
            dict(TEAM_ID=AWAY, PLAYER_ID=16, MIN="0:00"),
        ],
    )
    for period, start in ((2, 7200), (4, 21600), (5, 28800), (6, 31800)):
        case = add("period_{}_interval".format(period))
        for event in case["events"]:
            event["period"] = period
            if period > 4 and event["kind"] != "end":
                event["clock"] = str(int(event["clock"]) - 420)
        box(case, period=period, start=start, end=start + 100)
    case = add("fractional_first_event_interval")
    case["events"][1]["clock"] = "709.95"
    box(case, end=100)  # Original float truncation: int((720 - 709.95) * 10).
    case = add("opening_jump_skipped_in_interval")
    case["events"].insert(
        1, e("jump", 720, HOME, 1, winner_team=HOME, winner=2, opponent=11)
    )
    box(case)
    case = add("substitution_with_inferred_starters")
    case["events"].insert(3, e("sub", 650, HOME, 2, incoming=6))
    box(case)
    case = add("repair_retries_starter_recovery")
    case["events"][3:4] = [
        e("miss"),
        e("replay", 599, 0, 0),
        e("rebound", 598, AWAY, 11),
    ]
    box(case)
    for status, reason in (
        (404, "Not Found"),
        (429, "Too Many Requests"),
        (500, "Server Error"),
    ):
        box(
            add("http_{}".format(status), exception="HTTPError"),
            status=status,
            reason=reason,
            raw="recorded failure",
        )
    box(add("malformed_response_json", exception="JSONDecodeError"), raw="{")
    box(add("missing_response_result_sets", exception="KeyError"), raw="{}")
    malformed = players()
    malformed[0]["MIN"] = "bad"
    box(add("malformed_minutes", exception="IndexError"), rows=malformed)
    box(
        add("non_200_success_status", exception="UnboundLocalError"),
        status=204,
        reason="No Content",
        raw="",
    )
    return cases


def inputs(case):
    from tools.parity.exception_cases import v3_inputs

    raw, context = v3_inputs(case)
    context.period_starters = {}
    return raw, context


def response(record, url, params):
    assert record["params"] == params, (record["params"], params)
    result = requests.Response()
    result.status_code, result.reason = record["status"], record["reason"]
    result._content = record["body"].encode()
    result.request = requests.Request("GET", url, params=params).prepare()
    result.url = result.request.url
    return result


def original(case, folder, calls):
    from tools.parity.exception_cases import result_set, override_bytes
    from pbpstats.data_loader.stats_nba.possessions.file import (
        StatsNbaPossessionFileLoader,
    )
    from pbpstats.data_loader.stats_nba.possessions.loader import (
        StatsNbaPossessionLoader,
    )

    rows = encode_v2(case["events"])
    for directory in ("pbp", "game_details", "overrides"):
        (folder / directory).mkdir()
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
    for name, raw in override_bytes(case).items():
        (folder / "overrides" / name).write_bytes(raw)

    def recorded(url, params, **kwargs):
        calls.append(dict(url=url, params=deepcopy(params)))
        matches = [r for r in case["responses"].values() if r["params"] == params]
        assert (
            len(matches) == 1
        ), "No independently supplied response for original request"
        return response(matches[0], url, params)

    with patch(
        "pbpstats.resources.enhanced_pbp.start_of_period.requests.get", recorded
    ):
        return StatsNbaPossessionLoader(GAME, StatsNbaPossessionFileLoader(str(folder)))


def candidate(case):
    from pbpstats.data_loader.stats_nba_v3 import (
        StatsNbaV3PossessionLoader,
        V3Overrides,
        V3StarterBoxscore,
    )
    from tools.parity.exception_cases import override_bytes

    raw, context = inputs(case)
    boxes = {
        period: V3StarterBoxscore(
            record["body"].encode(),
            "Independent response fixture",
            context.pbp_sha256,
            record["params"],
            record["status"],
            record["reason"],
        )
        for period, record in case["responses"].items()
    }
    return StatsNbaV3PossessionLoader(
        raw,
        context,
        overrides=V3Overrides(
            override_bytes(case), "Independent correction fixture", context.pbp_sha256
        ),
        starter_boxscores=boxes,
    )


def observe(case, provider, folder):
    from tools.parity.worker import credit_snapshot

    calls = []
    if provider == "v2":
        loaded = original(case, folder, calls)
    else:
        loaded = candidate(case)
        calls = [
            dict(
                url="https://stats.nba.com/stats/boxscoretraditionalv2",
                params=d["request_params"],
            )
            for d in loaded.diagnostics
            if d["code"] == "recorded_starter_boxscore"
        ]
        raw, _ = inputs(case)
        assert loaded.decoded.source_bytes == raw
        assert loaded.decoded.context.period_starters == {}
        assert loaded.decoded.raw_rows == json.loads(raw)["game"]["actions"]
        assert sorted(i for e in loaded.events for i in e.v3_source_indices) == list(
            range(len(case["events"]))
        )
    return dict(
        requests=calls,
        credits=credit_snapshot(loaded),
        starters={
            e.period: e.period_starters for e in loaded.events if e.event_type == 12
        },
        events=[
            dict(number=e.event_num, lineup=e.current_players) for e in loaded.events
        ],
        possessions=[[e.event_num for e in p.events] for p in loaded.items],
    )
