"""Versioned rules for NBA V3 labels and clocks: technical, flagrant and voided free throws,
transition take fouls, and and-ones whose basket is recorded before its foul."""

import hashlib
import json

import pytest

from pbpstats.data_loader.stats_nba.possessions.loader import (
    TeamHasBackToBackPossessionsException,
)
from pbpstats.data_loader.stats_nba_v3 import StatsNbaV3PossessionLoader, V3Context, web
from pbpstats.data_loader.stats_nba_v3.decoder import (
    BLANK_FLAGRANT_FREE_THROW_VERSION,
    TEAMLESS_EXCESS_TIMEOUT_VERSION,
    TEAMLESS_TECHNICAL_VERSION,
    TECHNICAL_FREE_THROW_VERSION,
    TRANSITION_TAKE_FOUL_VERSION,
    VOIDED_SECOND_FREE_THROW_VERSION,
    V3DecodeError,
)
from pbpstats.data_loader.stats_nba_v3.possessions import AND_ONE_CLOCK_VERSION
from tools.parity.reference import ROOT
from tools.parity.scenarios import AWAY, HOME, e, encode_v3, wrap

DATA = ROOT / "tests/parity/data/recorded_evidence"
POR, PHX, SAC, NOP, UTA = 1610612757, 1610612756, 1610612758, 1610612740, 1610612762
WAS, CHI, TOR, MIN, OKC = 1610612764, 1610612741, 1610612761, 1610612750, 1610612760
GSW, DEN = 1610612744, 1610612743
WNBA = "1022600001"
RULES = (
    AND_ONE_CLOCK_VERSION, BLANK_FLAGRANT_FREE_THROW_VERSION, TEAMLESS_EXCESS_TIMEOUT_VERSION,
    TEAMLESS_TECHNICAL_VERSION, TECHNICAL_FREE_THROW_VERSION, TRANSITION_TAKE_FOUL_VERSION,
    VOIDED_SECOND_FREE_THROW_VERSION,
)


def load(rows, game="0022600001", validate_possessions=True):
    source = json.dumps({"game": {"gameId": game, "actions": rows}}).encode()
    roster = {
        p: {"team_id": team, "names": [f"Player{p}"]}
        for team, players in ((HOME, range(1, 9)), (AWAY, range(11, 19)))
        for p in players
    }
    context = V3Context(
        game, (HOME, AWAY), roster,
        {1: {HOME: [1, 2, 3, 4, 5], AWAY: [11, 12, 13, 14, 15]}},
        "Controlled label-rule context", hashlib.sha256(source).hexdigest(),
    )
    return StatsNbaV3PossessionLoader(source, context, validate_possessions=validate_possessions)


def number(rows, kind):
    return next(r["actionNumber"] for r in rows if r["actionType"] == kind)


def technical_foul(subtype="Defense 3 Second", and_one=False, team_recorded=False):
    """AWAY's technical-type foul while HOME has the ball; HOME's one free throw
    is recorded as "Free Throw 1 of 1", and HOME keeps the ball and scores.
    ``and_one`` adds a HOME basket and an AWAY shooting foul at the same clock.
    ``team_recorded`` records the foul with AWAY as its person and no team."""
    events = [e("make", 600, AWAY, 11)]
    if and_one:
        events += [e("make", 590, HOME, 2), e("foul", 590, AWAY, 13, subtype="Shooting")]
    events += [
        e("foul", 590, AWAY, 12, subtype=subtype),
        e("ft", 590, HOME, 1, attempt=1, total=1, made=True),
        e("make", 570, HOME, 3),
        e("make", 550, AWAY, 11),
    ]
    rows = encode_v3(wrap(events))
    foul = next(r for r in rows if r["subType"] == subtype)
    if team_recorded:
        foul.update(personId=AWAY, teamId=0, teamTricode="", description="AWAY Delay")
    return rows, number(rows, "Free Throw"), foul["actionNumber"]


@pytest.mark.parametrize("subtype, team_recorded", [
    ("Defense 3 Second", False),
    ("Hanging Technical", False),
    ("Technical", False),
    ("Flopping", False),
    # 0022600124 Q4 9:44: "THUNDER Delay", which version 2 did not see.
    ("Delay Technical", True),
])
def test_technical_foul_one_of_one_is_its_technical_free_throw(subtype, team_recorded):
    rows, ft, foul = technical_foul(subtype, team_recorded=team_recorded)
    loaded = load(rows)
    free_throw = next(x for x in loaded.events if x.event_num == ft)
    assert free_throw.sub_type == "Free Throw Technical" and free_throw.is_technical_ft
    assert free_throw.description == "Player1 Free Throw Technical (1 PTS)"
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    assert dict(
        code=TECHNICAL_FREE_THROW_VERSION, event_num=ft, foul_event_num=foul, foul=subtype,
        recorded="Free Throw 1 of 1", decoded="Free Throw Technical",
    ) in loaded.diagnostics
    assert TECHNICAL_FREE_THROW_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("game, subtype, and_one", [
    ("0022600001", "Defense 3 Second", True),
    ("0022600001", "Personal", False),
    ("1022600001", "Defense 3 Second", False),
], ids=["another_foul_at_the_clock", "not_a_technical_type_foul", "wnba"])
def test_technical_free_throw_rule_leaves_other_one_of_ones(game, subtype, and_one):
    rows, ft, _ = technical_foul(subtype, and_one)
    loaded = load(rows, game, validate_possessions=False)
    assert next(x for x in loaded.events if x.event_num == ft).sub_type == "Free Throw 1 of 1"
    assert not any(d["code"] == TECHNICAL_FREE_THROW_VERSION for d in loaded.diagnostics)


def take_foul(text="(P1.T2)", attempts=1):
    """AWAY's take foul on HOME, outside the penalty unless ``text`` says so,
    with ``attempts`` HOME free throws; HOME keeps the ball and scores."""
    events = [
        e("make", 600, AWAY, 11),
        e("foul", 590, AWAY, 12, subtype="Personal Take"),
    ] + [
        e("ft", 590, HOME, 1, attempt=attempt, total=attempts, made=True)
        for attempt in range(1, attempts + 1)
    ] + [e("make", 570, HOME, 3), e("make", 550, AWAY, 11)]
    rows = encode_v3(wrap(events))
    foul = next(r for r in rows if r["actionType"] == "Foul")
    foul["description"] = f"Player12 Personal Take Foul {text} (J.Doe)"
    return rows, foul["actionNumber"], number(rows, "Free Throw")


def test_personal_take_with_one_free_throw_is_a_transition_take_foul():
    rows, foul, ft = take_foul()
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows, game="1022600001")
    loaded = load(rows)
    take = next(x for x in loaded.events if x.event_num == foul)
    assert take.sub_type == "Transition Take" and take.is_transition_take_foul
    assert next(x for x in loaded.events if x.event_num == ft).is_transition_take_foul_ft
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    assert dict(
        code=TRANSITION_TAKE_FOUL_VERSION, event_num=foul, free_throw_event_num=ft,
        recorded="Personal Take", decoded="Transition Take",
    ) in loaded.diagnostics
    assert TRANSITION_TAKE_FOUL_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("text, attempts", [
    # 0022400814 Q4 0:06.9 and three earlier games: a take foul in the penalty,
    # its one recorded free throw coded a personal take in V2.
    ("(P5.PN)", 1),
    ("(P1.T2)", 2),
], ids=["in_the_penalty", "two_free_throws"])
def test_take_foul_rule_leaves_other_personal_take_fouls(text, attempts):
    rows, foul, _ = take_foul(text, attempts)
    loaded = load(rows, validate_possessions=False)
    assert next(x for x in loaded.events if x.event_num == foul).sub_type == "Personal Take"
    assert not any(d["code"] == TRANSITION_TAKE_FOUL_VERSION for d in loaded.diagnostics)


def test_recorded_2026_27_labels_decode_without_review():
    # 0022600092: Maluach's (Q1 7:32) and Krejci's (Q4 4:38) take fouls, and the
    # free throws for Williams III's (Q1 2:47) and Clingan's (Q3 7:51) defensive
    # three seconds.
    game = "0022600092"
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    assert game not in web.REVIEWED_CORRECTIONS
    loader = web.load_game(game, pbp, box, "recorded")
    rules = [
        (d["code"], d["event_num"]) for d in loader.diagnostics
        if d["code"] in (TECHNICAL_FREE_THROW_VERSION, TRANSITION_TAKE_FOUL_VERSION)
    ]
    assert rules == [
        (TRANSITION_TAKE_FOUL_VERSION, 52),
        (TECHNICAL_FREE_THROW_VERSION, 151),
        (TECHNICAL_FREE_THROW_VERSION, 422),
        (TRANSITION_TAKE_FOUL_VERSION, 686),
    ]
    assert loader.counts_by_team == {POR: 97, PHX: 96}
    rows = json.loads(pbp)["game"]["actions"]
    assert sorted(i for x in loader.events for i in x.v3_source_indices) == list(range(len(rows)))


@pytest.mark.parametrize("game, rules, checks, counts", [
    # 0022600100 Q4 8:14: Bey's free throw for Hayes' rim-hanging technical.
    ("0022600100", [(TECHNICAL_FREE_THROW_VERSION, 595)], [(595, "is_technical_ft", True)],
     {UTA: 102, NOP: 102}),
    # 0022600103 Q2 1:19: Sacramento's short timeout, V2's 9/2; and a free throw
    # for a defensive three seconds.
    ("0022600103", [(TECHNICAL_FREE_THROW_VERSION, 594)], [(354, "sub_type", "Short")],
     {POR: 105, SAC: 104}),
    # 0022600108 Q2 5:25: a free throw for a defensive three seconds; Q4 3:32 and
    # 1:19: Powell's and Young's free throws for Young's and Buzelis' flopping.
    ("0022600108", [(TECHNICAL_FREE_THROW_VERSION, n) for n in (290, 693, 732)],
     [(693, "is_technical_ft", True), (732, "is_technical_ft", True)], {WAS: 104, CHI: 105}),
    # 0022600115 Q3 1:21: Quickley's free throw for Shannon Jr's flopping.
    ("0022600115", [(TECHNICAL_FREE_THROW_VERSION, 522)], [(522, "is_technical_ft", True)],
     {TOR: 97, MIN: 98}),
    # 0022600124 Q4 9:44: Booker's free throw for "THUNDER Delay", recorded with
    # the team as its person.
    ("0022600124", [(TECHNICAL_FREE_THROW_VERSION, 571)], [(571, "is_technical_ft", True)],
     {PHX: 97, OKC: 97}),
    # 0022600127 Q4 8:34: Gordon's "Second Technical" ejection, V2's 11/1; and Q3
    # 1:13 a free throw for a defensive three seconds.
    ("0022600127", [(TECHNICAL_FREE_THROW_VERSION, 518)], [(625, "sub_type", "Second Technical")],
     {GSW: 95, DEN: 95}),
])
def test_recorded_2026_27_technical_free_throws_and_pre_2017_labels(game, rules, checks, counts):
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    assert game not in web.REVIEWED_CORRECTIONS
    loader = web.load_game(game, pbp, box, "recorded")
    assert [
        (d["code"], d["event_num"]) for d in loader.diagnostics
        if d["code"] in (TECHNICAL_FREE_THROW_VERSION, TRANSITION_TAKE_FOUL_VERSION)
    ] == rules
    for event, attribute, value in checks:
        assert getattr(next(x for x in loader.events if x.event_num == event), attribute) == value
    assert loader.counts_by_team == counts


def and_one(early=1, foul="Shooting", shooter=1, between=None):
    """HOME's basket ``early`` seconds before AWAY's ``foul`` at 9:50 and
    ``shooter``'s made free throw 1 of 1 there, with a HOME substitution at
    ``between`` between the basket and the foul; AWAY then scores."""
    events = [e("make", 600, AWAY, 11), e("make", 590 + early, HOME, 1)]
    if between is not None:
        events.append(e("sub", between, HOME, 3, incoming=6))
    events += [
        e("foul", 590, AWAY, 12, subtype=foul),
        e("ft", 590, HOME, shooter, attempt=1, total=1, made=True),
        e("make", 570, AWAY, 11),
    ]
    rows = encode_v3(wrap(events))
    basket = next(r for r in rows if r["actionType"] == "Made Shot" and r["teamId"] == HOME)
    return rows, basket["actionNumber"], number(rows, "Foul"), number(rows, "Free Throw")


@pytest.mark.parametrize("early, foul, shooter, between, recorded", [
    (1, "Shooting", 1, None, "9:51"),
    (2, "Shooting Block", 1, None, "9:52"),
    (0.2, "Loose Ball", 2, None, "9:50.2"),
    (1, "Shooting", 1, 590, "9:51"),
], ids=["shooting_foul", "shooting_block_two_seconds", "loose_ball_teammate",
        "substitution_between"])
def test_basket_recorded_before_its_and_one_foul_takes_the_foul_clock(
    early, foul, shooter, between, recorded
):
    rows, basket, fouled, ft = and_one(early, foul, shooter, between)
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows, game=WNBA)
    loaded = load(rows)
    shot = next(x for x in loaded.events if x.event_num == basket)
    assert shot.clock == "9:50" and shot.is_make_that_does_not_end_possession
    trip = next(p for p in loaded.items if shot in p.events)
    assert trip.offense_team_id == HOME and trip.events[-1].event_num == ft
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    assert dict(
        code=AND_ONE_CLOCK_VERSION, event_num=basket, foul_event_num=fouled,
        free_throw_event_num=ft, recorded=recorded, decoded="9:50",
    ) in loaded.diagnostics
    assert AND_ONE_CLOCK_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("game, early, foul, shooter, between", [
    ("0022600001", 2.1, "Shooting", 1, None),
    ("0022600001", 1, "Away From Play", 2, None),
    ("0022600001", 1, "Shooting", 2, None),
    ("0022600001", 1, "Shooting", 1, 591),
    (WNBA, 1, "Shooting", 1, None),
], ids=["over_two_seconds", "not_an_and_one_foul", "free_throw_not_the_shooters",
        "substitution_at_the_basket_clock", "wnba"])
def test_and_one_clock_rule_leaves_other_baskets(game, early, foul, shooter, between):
    rows, basket, _, _ = and_one(early, foul, shooter, between)
    loaded = load(rows, game, validate_possessions=False)
    assert next(x for x in loaded.events if x.event_num == basket).clock != "9:50"
    assert not any(d["code"] == AND_ONE_CLOCK_VERSION for d in loaded.diagnostics)


def test_and_one_clock_rule_needs_the_teams_lone_free_throw():
    rows, basket, _, ft = and_one()
    throw = next(r for r in rows if r["actionNumber"] == ft)
    rows.insert(rows.index(throw) + 1, dict(throw, actionNumber=999, actionId=999))
    loaded = load(rows, validate_possessions=False)
    assert next(x for x in loaded.events if x.event_num == basket).clock == "9:51"
    assert not any(d["code"] == AND_ONE_CLOCK_VERSION for d in loaded.diagnostics)


def flagrant_trip(attempts=3, foul="Flagrant Type 1", shooters=(1, 1, 1)):
    """AWAY's ``foul`` gives HOME ``attempts`` free throws, by ``shooters``, the
    first missed, and the ball; the feed records each with no subtype and text
    that numbers neither. HOME then scores."""
    events = [e("make", 600, AWAY, 11), e("foul", 590, AWAY, 12, subtype=foul)]
    events += [
        e("ft", 590, HOME, shooters[k], attempt=k + 1, total=attempts, made=k > 0)
        for k in range(attempts)
    ]
    rows = encode_v3(wrap(events + [e("make", 570, HOME, 2), e("make", 550, AWAY, 11)]))
    throws = [r for r in rows if r["actionType"] == "Free Throw"]
    for throw in throws:
        made = not throw["description"].startswith("MISS ")
        throw.update(subType="", description="{}Player{} Free Throw{}".format(
            "" if made else "MISS ", throw["personId"], " (1 PTS)" if made else ""
        ))
    return rows, [throw["actionNumber"] for throw in throws], number(rows, "Foul")


@pytest.mark.parametrize("attempts", [1, 2, 3])
def test_blank_flagrant_free_throws_are_their_trips_attempts(attempts):
    rows, throws, foul = flagrant_trip(attempts)
    with pytest.raises(V3DecodeError, match="Unsupported free throw subtype"):
        load(rows, game=WNBA)
    loaded = load(rows)
    for attempt, event in enumerate(throws, 1):
        label = "Free Throw Flagrant {} of {}".format(attempt, attempts)
        throw = next(x for x in loaded.events if x.event_num == event)
        assert throw.sub_type == label
        assert label in throw.description
        assert dict(
            code=BLANK_FLAGRANT_FREE_THROW_VERSION, event_num=event, foul_event_num=foul,
            recorded="", decoded=label,
        ) in loaded.diagnostics
    # The flagrant trip keeps the ball: HOME's basket is in it.
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    assert BLANK_FLAGRANT_FREE_THROW_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("change", [
    dict(foul="Flagrant Type 2"),
    dict(foul="Personal"),
    dict(shooters=(1, 2, 1)),
], ids=["flagrant_2", "not_a_flagrant", "two_shooters"])
def test_blank_flagrant_rule_leaves_other_blank_free_throws(change):
    rows, _, _ = flagrant_trip(**change)
    with pytest.raises(V3DecodeError, match="Unsupported free throw subtype"):
        load(rows)


def voided_second(made=True, foul="Shooting", turnover="Offensive Goaltending", basket=None):
    """AWAY's ``foul`` gives HOME two free throws: Player1's first, recorded as 1
    of 1, is ``made``, and Player2's ``turnover`` voids the second. ``basket``
    puts a HOME basket that many seconds before the foul. AWAY then scores."""
    events = [e("make", 600, AWAY, 11)]
    if basket is not None:
        events.append(e("make", 590 + basket, HOME, 3))
    events += [
        e("foul", 590, AWAY, 12, subtype=foul),
        e("ft", 590, HOME, 1, attempt=1, total=1, made=made),
        e("turnover", 590, HOME, 2, subtype=turnover),
        e("make", 570, AWAY, 11),
    ]
    rows = encode_v3(wrap(events))
    return rows, number(rows, "Free Throw"), number(rows, "Foul"), number(rows, "Turnover")


@pytest.mark.parametrize("turnover", ["Offensive Goaltending", "Lane Violation"])
def test_made_one_of_one_before_a_voiding_violation_is_one_of_two(turnover):
    rows, ft, foul, voiding = voided_second(turnover=turnover)
    with pytest.raises(TeamHasBackToBackPossessionsException):
        load(rows, game=WNBA)
    loaded = load(rows)
    throw = next(x for x in loaded.events if x.event_num == ft)
    assert throw.sub_type == "Free Throw 1 of 2" and not throw.is_possession_ending_event
    assert "Free Throw 1 of 2" in throw.description
    trip = next(p for p in loaded.items if throw in p.events)
    assert trip.offense_team_id == HOME and trip.events[-1].event_num == voiding
    assert [p.offense_team_id for p in loaded.items] == [AWAY, HOME, AWAY, HOME]
    assert dict(
        code=VOIDED_SECOND_FREE_THROW_VERSION, event_num=ft, foul_event_num=foul,
        turnover_event_num=voiding, recorded="Free Throw 1 of 1", decoded="Free Throw 1 of 2",
    ) in loaded.diagnostics
    assert VOIDED_SECOND_FREE_THROW_VERSION in loaded.capabilities["extensions"]
    assert loaded.decoded.raw_rows == rows


@pytest.mark.parametrize("change", [
    dict(made=False),
    dict(foul="Away From Play"),
    dict(turnover="Bad Pass"),
    dict(basket=0),
    dict(basket=2),
], ids=["missed", "not_a_shooting_foul", "not_a_voiding_turnover", "and_one",
        "and_one_basket_recorded_early"])
def test_voided_free_throw_rule_leaves_other_one_of_ones(change):
    rows, ft, _, _ = voided_second(**change)
    loaded = load(rows, validate_possessions=False)
    throw = next(x for x in loaded.events if x.event_num == ft)
    assert throw.sub_type == "Free Throw 1 of 1"
    assert not any(d["code"] == VOIDED_SECOND_FREE_THROW_VERSION for d in loaded.diagnostics)


def test_voided_free_throw_rule_needs_the_violation_after_the_free_throw():
    rows, ft, _, voiding = voided_second()
    turnover = next(r for r in rows if r["actionNumber"] == voiding)
    rows.remove(turnover)
    rows.insert(rows.index(next(r for r in rows if r["actionNumber"] == ft)), turnover)
    loaded = load(rows, validate_possessions=False)
    throw = next(x for x in loaded.events if x.event_num == ft)
    assert throw.sub_type == "Free Throw 1 of 1"


@pytest.mark.parametrize("game, rules, trip, offense, counts, checks", [
    # 0022000042 Q3 5:06: Brooklyn's delay technical, recorded without a team.
    ("0022000042", [(TEAMLESS_TECHNICAL_VERSION, 439)], [439, 440, 441, 442, 445, 447],
     1610612763, {1610612763: 109, 1610612751: 110}, [(439, "team_id", 1610612751)]),
    # 0022000215 Q4 2:22, 0022000285 Q4 0:27.5, 0022101135 Q4 0:10 and 0022200323
    # Q4 1:24: excess timeout turnovers, and 0022000285's technical too,
    # recorded without a team.
    ("0022000215", [(TEAMLESS_EXCESS_TIMEOUT_VERSION, 713)], [681, 683, 713], 1610612764,
     {1610612764: 101, 1610612766: 100}, [(713, "team_id", 1610612764)]),
    ("0022000285", [(TEAMLESS_EXCESS_TIMEOUT_VERSION, 629), (TEAMLESS_EXCESS_TIMEOUT_VERSION, 630)],
     [629, 630], 1610612746, {1610612748: 98, 1610612746: 97},
     [(629, "team_id", 1610612746), (630, "team_id", 1610612746)]),
    ("0022101135", [(TEAMLESS_EXCESS_TIMEOUT_VERSION, 644)], [643, 644], 1610612762,
     {1610612762: 94, 1610612746: 93}, [(644, "team_id", 1610612762)]),
    ("0022200323", [(TEAMLESS_EXCESS_TIMEOUT_VERSION, 724)], [718, 719, 720, 723, 724],
     1610612754, {1610612754: 112, 1610612758: 113}, [(724, "team_id", 1610612754)]),
    # 0022300866 Q3 4:03, 0022600002 Q2 4:12, 0022600089 Q1 8:10 and 0022600101
    # Q4 3:33: and-ones whose basket V3 records a second early. 0022600096 Q2
    # 9:59: a loose ball foul and Lyles' free throw as Gobert's basket, recorded
    # two seconds early, went in. 0022600002 Q2 0:11.9: Brunson's free throw for
    # a defensive three seconds, labeled 1 of 1; New York kept the ball.
    ("0022300866", [(AND_ONE_CLOCK_VERSION, 433)], [431, 432, 433, 435, 437, 439], 1610612751,
     {1610612751: 93, 1610612737: 93}, [(433, "clock", "4:03")]),
    ("0022600002", [(AND_ONE_CLOCK_VERSION, 330), (TECHNICAL_FREE_THROW_VERSION, 412)],
     [330, 331, 333], 1610612752, {1610612755: 102, 1610612752: 102},
     [(330, "clock", "4:12"), (412, "is_possession_ending_event", False),
      (412, "is_technical_ft", True)]),
    ("0022600089", [(AND_ONE_CLOCK_VERSION, 45)], [44, 45, 47, 49, 50], 1610612762,
     {1610612763: 104, 1610612762: 103}, [(45, "clock", "8:10")]),
    ("0022600096", [(AND_ONE_CLOCK_VERSION, 194)], [194, 196, 198, 199], 1610612750,
     {1610612753: 100, 1610612750: 100}, [(194, "clock", "9:59")]),
    ("0022600101", [(AND_ONE_CLOCK_VERSION, 772)], [772, 774, 776], 1610612763,
     {1610612763: 97, 1610612744: 98}, [(772, "clock", "3:33")]),
    # 0022400512 Q4 3:21, 0022500054 Q2 11:06 and 0022501009 Q1 0:47: a made
    # first free throw logged 1 of 1, the second voided by offensive goaltending
    # or a lane violation.
    ("0022400512", [(VOIDED_SECOND_FREE_THROW_VERSION, 634)], [588, 634, 658], 1610612764,
     {1610612764: 90, 1610612755: 90}, [(634, "is_ft_1_of_2", True)]),
    ("0022500054", [(VOIDED_SECOND_FREE_THROW_VERSION, 192)], [190, 192, 262], 1610612745,
     {1610612743: 91, 1610612745: 93}, [(192, "is_ft_1_of_2", True)]),
    ("0022501009", [(VOIDED_SECOND_FREE_THROW_VERSION, 182)], [158, 182, 674], 1610612764,
     {1610612764: 98, 1610612765: 98}, [(182, "is_ft_1_of_2", True)]),
    # 0022400625 Q4 9:43: Jal. Williams' transition take foul, labeled Personal Take.
    ("0022400625", [(TRANSITION_TAKE_FOUL_VERSION, 615)], [615, 617, 618, 619], 1610612742,
     {1610612742: 99, 1610612760: 100}, [(615, "is_transition_take_foul", True)]),
    # 0022600091 Q4 11:37 and 0022600099 Q2 9:46: three flagrant free throws
    # recorded with neither category nor numbering; 0022600091 Q1 2:47 Eason's
    # "First Flagrant Type 2" ejection, V2's 11/3, and Q3 9:43 Sengun's
    # transition take foul labeled "Personal Take".
    ("0022600091", [(TRANSITION_TAKE_FOUL_VERSION, 413)] + [
        (BLANK_FLAGRANT_FREE_THROW_VERSION, n) for n in (566, 569, 570)],
     [562, 564, 567, 566, 568, 569, 570, 571], 1610612742, {1610612745: 98, 1610612742: 99},
     [(130, "sub_type", "First Flagrant Type 2"), (413, "is_transition_take_foul", True),
      (566, "sub_type", "Free Throw Flagrant 1 of 3"),
      (570, "sub_type", "Free Throw Flagrant 3 of 3")]),
    ("0022600099", [(BLANK_FLAGRANT_FREE_THROW_VERSION, n) for n in (235, 239, 240)],
     [233, 238, 235, 239, 240, 259, 241, 242], 1610612741, {1610612741: 110, 1610612749: 109},
     [(235, "sub_type", "Free Throw Flagrant 1 of 3"),
      (240, "sub_type", "Free Throw Flagrant 3 of 3")]),
])
def test_recorded_games_decode_without_review(game, rules, trip, offense, counts, checks):
    """Games once corrected by reviewed entries, which versioned rules now decode."""
    pbp = (DATA / f"stats_v3_{game}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game}.json").read_bytes()
    live = DATA / f"live_{game}.json"
    fetch = (lambda url: web.SavedResponse(live.read_bytes(), url)) if live.exists() else None
    assert game not in web.REVIEWED_CORRECTIONS
    loader = web.load_game(game, pbp, box, "recorded", fetch_live=fetch)
    assert [(d["code"], d["event_num"]) for d in loader.diagnostics if d["code"] in RULES] == rules
    possession = next(p for p in loader.items if any(x.event_num == trip[0] for x in p.events))
    assert [x.event_num for x in possession.events] == trip
    assert possession.offense_team_id == offense
    assert loader.counts_by_team == counts
    for event, attribute, value in checks:
        assert getattr(next(x for x in loader.events if x.event_num == event), attribute) == value
    rows = json.loads(pbp)["game"]["actions"]
    assert sorted(i for x in loader.events for i in x.v3_source_indices) == list(range(len(rows)))
