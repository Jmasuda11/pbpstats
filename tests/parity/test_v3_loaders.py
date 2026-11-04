"""The V3 provider's loaders take a game ID and a source loader, as the original's do.

File and web sources give the same game as ``web.load_game`` with the same
recorded responses, evidence and reviewed correction, and ``Client`` loads
every V3 resource.
"""

import json
import shutil

import pytest
import requests
import responses

from pbpstats.client import Client
from pbpstats.data_loader import (
    StatsNbaV3BoxscoreFileLoader,
    StatsNbaV3BoxscoreLoader,
    StatsNbaV3EnhancedPbpFileLoader,
    StatsNbaV3EnhancedPbpLoader,
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
    StatsNbaV3PossessionFileLoader,
    StatsNbaV3PossessionLoader,
    StatsNbaV3PossessionWebLoader,
)
from pbpstats.data_loader.factory import DataLoaderFactory
from pbpstats.data_loader.stats_nba.base import StatsNbaLoaderBase
from pbpstats.data_loader.stats_nba.enhanced_pbp.loader import StatsNbaEnhancedPbpLoader
from pbpstats.data_loader.stats_nba.pbp.loader import StatsNbaPbpLoader
from pbpstats.data_loader.stats_nba.possessions.loader import (
    TeamHasBackToBackPossessionsException,
)
from pbpstats.data_loader.stats_nba_v3 import (
    V3DecodeError,
    V3EvidenceRequired,
    V3JumpBallEvidenceRequired,
    web,
)
from pbpstats.data_loader.stats_nba_v3.base import StatsNbaV3LoaderBase
from pbpstats.data_loader.stats_nba_v3.decoder import live_play_by_play_url
from pbpstats.objects.game import Game
from pbpstats.resources.boxscore.boxscore import Boxscore
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_factory import (
    StatsNbaV3EnhancedPbpFactory,
)
from pbpstats.resources.enhanced_pbp.stats_nba_v3.team_heave import V3TeamHeave
from tools.parity.reference import ROOT

DATA = ROOT / "tests/parity/data/recorded_evidence"
PLAIN, LIVE, STARTERS, CORRECTED, ALIAS = (
    "0022500089",
    "0022500100",
    "0022000637",
    "0021900156",
    "0022500288",
)


def data_directory(root, game_id):
    """A data directory with a game's recorded responses where the file sources read them."""
    for folder in ("pbp", "game_details"):
        (root / folder).mkdir(exist_ok=True)
    shutil.copytree(ROOT / "overrides_v3", root / "overrides_v3", dirs_exist_ok=True)
    shutil.copy(DATA / f"stats_v3_{game_id}.json", root / "pbp")
    shutil.copy(DATA / f"stats_v3_boxscore_{game_id}.json", root / "game_details")
    if (DATA / f"live_{game_id}.json").exists():
        shutil.copy(DATA / f"live_{game_id}.json", root / "pbp")
    for path in DATA.glob(f"stats_boxscoretraditionalv2_{game_id}_period_*.json"):
        shutil.copy(path, root / "game_details")
    return root


def recorded_game(game_id, aliases=None):
    """The game as ``web.load_game`` parses it with every recorded response."""
    pbp = (DATA / f"stats_v3_{game_id}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{game_id}.json").read_bytes()
    live = DATA / f"live_{game_id}.json"

    def fetch_boxscore(period, url, params):
        path = DATA / f"stats_boxscoretraditionalv2_{game_id}_period_{period}.json"
        return web.SavedResponse(path.read_bytes(), url)

    return web.load_game(
        game_id,
        pbp,
        box,
        "recorded",
        fetch_boxscore=fetch_boxscore,
        aliases=aliases,
        overrides=web.reviewed_overrides(ROOT, game_id, pbp),
        live=web.SavedResponse(live.read_bytes(), live_play_by_play_url(game_id))
        if live.exists()
        else None,
    )


def as_json(loader):
    return json.loads(json.dumps(web.possessions_json(loader)))


def fouls_with_no_fouled_player(loader):
    return [u for u in loader.decoded.unknown_attribution if u["role"] == "foul_drawn"]


@pytest.mark.parametrize("game_id", [PLAIN, LIVE, STARTERS, CORRECTED])
def test_file_source_gives_the_game_load_game_gives(tmp_path, game_id):
    source = StatsNbaV3PossessionFileLoader(str(data_directory(tmp_path, game_id)))
    loader = StatsNbaV3PossessionLoader(game_id, source)
    assert as_json(loader) == as_json(recorded_game(game_id))


def test_file_source_reads_override_files_from_the_v3_folder(tmp_path):
    directory = data_directory(tmp_path, CORRECTED)
    shutil.move(str(directory / "overrides_v3"), str(directory / "overrides"))
    with pytest.raises(TeamHasBackToBackPossessionsException):
        StatsNbaV3PossessionLoader(CORRECTED, StatsNbaV3PossessionFileLoader(str(directory)))


def test_evidence_is_read_only_when_the_parse_asks_for_it(tmp_path):
    directory = data_directory(tmp_path, LIVE)
    codes = [d["code"] for d in StatsNbaV3PossessionLoader(
        LIVE, StatsNbaV3PossessionFileLoader(str(directory))
    ).diagnostics]
    assert "recorded_live_input" in codes and "recorded_starter_boxscore" not in codes
    codes = [d["code"] for d in StatsNbaV3PossessionLoader(
        PLAIN, StatsNbaV3PossessionFileLoader(str(data_directory(tmp_path, PLAIN)))
    ).diagnostics]
    assert "recorded_live_input" not in codes


def test_missing_recorded_evidence_names_its_file(tmp_path):
    (tmp_path / "live").mkdir()
    directory = data_directory(tmp_path / "live", LIVE)
    (directory / "pbp" / f"live_{LIVE}.json").unlink()
    with pytest.raises(V3JumpBallEvidenceRequired, match=f"live_{LIVE}.json does not exist"):
        StatsNbaV3PossessionLoader(LIVE, StatsNbaV3PossessionFileLoader(str(directory)))
    (tmp_path / "starters").mkdir()
    directory = data_directory(tmp_path / "starters", STARTERS)
    for path in (directory / "game_details").glob("stats_boxscoretraditionalv2_*"):
        path.unlink()
    with pytest.raises(V3EvidenceRequired, match="_period_5.json does not exist") as needed:
        StatsNbaV3PossessionLoader(STARTERS, StatsNbaV3PossessionFileLoader(str(directory)))
    assert needed.value.period == 5 and needed.value.params["GameId"] == STARTERS


def test_file_source_reads_any_live_play_by_play_for_its_fouled_players(tmp_path):
    (tmp_path / "live").mkdir()
    (tmp_path / "plain").mkdir()
    directory = data_directory(tmp_path / "live", LIVE)
    loader = StatsNbaV3PossessionLoader(LIVE, StatsNbaV3PossessionFileLoader(str(directory)))
    assert not fouls_with_no_fouled_player(loader)
    directory = data_directory(tmp_path / "plain", PLAIN)
    loader = StatsNbaV3PossessionLoader(PLAIN, StatsNbaV3PossessionFileLoader(str(directory)))
    assert len(fouls_with_no_fouled_player(loader)) == 46


def test_reviewed_aliases_come_from_the_overrides_folder(tmp_path):
    directory = data_directory(tmp_path, ALIAS)
    source = StatsNbaV3PossessionFileLoader(str(directory))
    with pytest.raises(V3DecodeError, match="'Hansen' is unresolved"):
        StatsNbaV3PossessionLoader(ALIAS, source)
    # As an import applies them, an alias for anyone outside the box score is left out.
    (directory / "overrides_v3" / "player_aliases.json").write_text(
        json.dumps({"1642905": ["Hansen"], "1": ["Nobody"]}), encoding="utf-8"
    )
    loader = StatsNbaV3PossessionLoader(ALIAS, source)
    assert as_json(loader) == as_json(recorded_game(ALIAS, {1642905: ["Hansen"]}))


@responses.activate
def test_web_source_saves_the_exact_bytes_the_file_source_reads(tmp_path):
    pbp = (DATA / f"stats_v3_{LIVE}.json").read_bytes()
    box = (DATA / f"stats_v3_boxscore_{LIVE}.json").read_bytes()
    live = (DATA / f"live_{LIVE}.json").read_bytes()
    base = web.stats_url(LIVE)
    responses.add(responses.GET, base + "playbyplayv3", body=pbp)
    responses.add(responses.GET, base + "boxscoretraditionalv3", body=box)
    responses.add(responses.GET, live_play_by_play_url(LIVE), body=live)
    for folder in ("pbp", "game_details"):
        (tmp_path / folder).mkdir()
    fetched = StatsNbaV3PossessionLoader(LIVE, StatsNbaV3PossessionWebLoader(str(tmp_path)))
    first = responses.calls[0].request
    assert "GameID=" + LIVE in first.url and first.headers["User-Agent"] == web.HEADERS["User-Agent"]
    assert (tmp_path / "pbp" / f"stats_v3_{LIVE}.json").read_bytes() == pbp
    assert (tmp_path / "game_details" / f"stats_v3_boxscore_{LIVE}.json").read_bytes() == box
    assert (tmp_path / "pbp" / f"live_{LIVE}.json").read_bytes() == live
    saved = StatsNbaV3PossessionLoader(LIVE, StatsNbaV3PossessionFileLoader(str(tmp_path)))
    assert as_json(fetched) == as_json(saved) == as_json(recorded_game(LIVE))
    # Its fouled players and its undecided jump ball read one response.
    assert not fouls_with_no_fouled_player(fetched)
    assert sum(c.request.url == live_play_by_play_url(LIVE) for c in responses.calls) == 1


def plain_game_responses(live_response):
    base = web.stats_url(PLAIN)
    responses.add(responses.GET, base + "playbyplayv3",
                  body=(DATA / f"stats_v3_{PLAIN}.json").read_bytes())
    responses.add(responses.GET, base + "boxscoretraditionalv3",
                  body=(DATA / f"stats_v3_boxscore_{PLAIN}.json").read_bytes())
    responses.add(responses.GET, live_play_by_play_url(PLAIN), **live_response)


@responses.activate
def test_web_source_goes_without_fouled_players_for_a_game_the_host_refuses(tmp_path):
    for folder in ("pbp", "game_details"):
        (tmp_path / folder).mkdir()
    plain_game_responses(dict(status=403))
    loader = StatsNbaV3PossessionLoader(PLAIN, StatsNbaV3PossessionWebLoader(str(tmp_path)))
    assert len(fouls_with_no_fouled_player(loader)) == 46
    assert not (tmp_path / "pbp" / f"live_{PLAIN}.json").exists()


@responses.activate
def test_web_source_does_not_take_a_failed_live_request_for_a_refusal():
    plain_game_responses(dict(status=500))
    with pytest.raises(requests.HTTPError):
        StatsNbaV3PossessionLoader(PLAIN, StatsNbaV3PossessionWebLoader())


@responses.activate
def test_web_source_saves_the_original_period_start_request(tmp_path):
    (tmp_path / "pbp").mkdir()
    (tmp_path / "game_details").mkdir()
    base = web.stats_url(STARTERS)
    responses.add(responses.GET, base + "playbyplayv3",
                  body=(DATA / f"stats_v3_{STARTERS}.json").read_bytes())
    responses.add(responses.GET, base + "boxscoretraditionalv3",
                  body=(DATA / f"stats_v3_boxscore_{STARTERS}.json").read_bytes())
    period = (DATA / f"stats_boxscoretraditionalv2_{STARTERS}_period_5.json").read_bytes()
    responses.add(responses.GET, base + "boxscoretraditionalv2", body=period)
    responses.add(responses.GET, live_play_by_play_url(STARTERS), status=403)
    fetched = StatsNbaV3PossessionLoader(STARTERS, StatsNbaV3PossessionWebLoader(str(tmp_path)))
    request = next(c.request for c in responses.calls if "boxscoretraditionalv2" in c.request.url)
    assert "RangeType=2" in request.url and "GameId=" + STARTERS in request.url
    name = f"stats_boxscoretraditionalv2_{STARTERS}_period_5.json"
    assert (tmp_path / "game_details" / name).read_bytes() == period
    # The evidence records the request it answered: here its full URL.
    fetched, recorded = as_json(fetched), as_json(recorded_game(STARTERS))
    for data, source in ((fetched, request.url), (recorded, request.url.split("?")[0])):
        for diagnostic in data["diagnostics"]:
            if diagnostic["code"] == "recorded_starter_boxscore":
                assert diagnostic.pop("source") == source
    assert fetched == recorded


def test_pbp_and_boxscore_resources_keep_the_recorded_rows(tmp_path):
    directory = str(data_directory(tmp_path, PLAIN))
    actions = json.loads((DATA / f"stats_v3_{PLAIN}.json").read_bytes())["game"]["actions"]
    pbp = StatsNbaV3PbpLoader(PLAIN, StatsNbaV3PbpFileLoader(directory))
    assert [item.actionNumber for item in pbp.items] == [a["actionNumber"] for a in actions]
    assert pbp.items[3].data["order"] == 3
    box = json.loads((DATA / f"stats_v3_boxscore_{PLAIN}.json").read_bytes())["boxScoreTraditional"]
    loader = StatsNbaV3BoxscoreLoader(PLAIN, StatsNbaV3BoxscoreFileLoader(directory))
    home, away = box["homeTeam"], box["awayTeam"]
    boxscore = Boxscore(loader.items)
    assert len(boxscore.player_items) == len(home["players"]) + len(away["players"])
    assert [team["team_id"] for team in boxscore.team_items] == [box["homeTeamId"], box["awayTeamId"]]
    player = away["players"][0]
    assert boxscore.player_team_map[player["personId"]] == box["awayTeamId"]
    assert boxscore.player_name_map[player["personId"]] == (
        player["firstName"] + " " + player["familyName"]
    )
    totals = boxscore.team_items[0]
    assert totals["points"] == home["statistics"]["points"]
    assert totals["team_abbreviation"] == home["teamTricode"]


def test_a_box_score_for_another_game_is_rejected(tmp_path):
    directory = data_directory(tmp_path, PLAIN)
    path = directory / "game_details" / f"stats_v3_boxscore_{PLAIN}.json"
    box = json.loads(path.read_bytes())
    box["boxScoreTraditional"]["gameId"] = "0022500001"
    path.write_text(json.dumps(box), encoding="utf-8")
    with pytest.raises(V3DecodeError, match="Box score is for another game"):
        StatsNbaV3BoxscoreLoader(PLAIN, StatsNbaV3BoxscoreFileLoader(str(directory)))
    with pytest.raises(V3DecodeError, match="Box score is for another game"):
        StatsNbaV3PossessionLoader(PLAIN, StatsNbaV3PossessionFileLoader(str(directory)))


@pytest.fixture
def game_class():
    """Client sets its loaders on the shared Game class, as the original's does;
    the test starts from a bare class, and the class is put back after so
    neither earlier nor later tests' clients load the other's resources."""
    saved = {k: v for k, v in vars(Game).items() if not k.startswith("__")}
    for name in saved:
        delattr(Game, name)
    yield
    for name in [k for k in vars(Game) if not k.startswith("__")]:
        delattr(Game, name)
    for name, value in saved.items():
        setattr(Game, name, value)


def test_client_loads_every_v3_resource(tmp_path, game_class):
    directory = str(data_directory(tmp_path, PLAIN))
    resources = ("Pbp", "Boxscore", "EnhancedPbp", "Possessions")
    for resource in resources:
        found = DataLoaderFactory().get_data_loader("stats_nba_v3", resource)
        assert [x["loader"].data_provider for x in found] == ["stats_nba_v3"]
    client = Client(dict(
        dir=directory,
        **{r: {"source": "file", "data_provider": "stats_nba_v3"} for r in resources},
    ))
    game = client.Game(PLAIN)
    loader = StatsNbaV3PossessionLoader(PLAIN, StatsNbaV3PossessionFileLoader(directory))
    enhanced = StatsNbaV3EnhancedPbpLoader(PLAIN, StatsNbaV3EnhancedPbpFileLoader(directory))
    assert len(game.possessions.items) == len(loader.items)
    assert [e.event_num for e in game.enhanced_pbp.items] == [e.event_num for e in enhanced.items]
    assert len(game.pbp.items) == len(StatsNbaV3PbpLoader(PLAIN, StatsNbaV3PbpFileLoader(directory)).items)
    assert len(game.boxscore.player_items) == len(
        StatsNbaV3BoxscoreLoader(PLAIN, StatsNbaV3BoxscoreFileLoader(directory)).items
    ) - 2


def test_client_keeps_detailed_statistics_gated(tmp_path, game_class):
    directory = str(data_directory(tmp_path, PLAIN))
    client = Client(dict(
        dir=directory, Possessions={"source": "file", "data_provider": "stats_nba_v3"}
    ))
    possessions = client.Game(PLAIN).possessions
    for name in ("team_stats", "opponent_stats", "player_stats", "lineup_stats", "lineup_opponent_stats"):
        with pytest.raises(V3DecodeError, match="attribution completeness"):
            getattr(possessions, name)


def test_client_gives_detailed_statistics_for_a_game_with_every_fouled_player(
    tmp_path, game_class
):
    directory = str(data_directory(tmp_path, LIVE))
    client = Client(dict(
        dir=directory, Possessions={"source": "file", "data_provider": "stats_nba_v3"}
    ))
    possessions = client.Game(LIVE).possessions
    loader = StatsNbaV3PossessionLoader(LIVE, StatsNbaV3PossessionFileLoader(directory))
    assert loader.capabilities["detailed_event_stats"] == "available"
    for team, count in loader.counts_by_team.items():
        assert {
            row["stat_value"]
            for row in possessions.team_stats
            if row["team_id"] == team and row["stat_key"] == "OffPoss"
        } == {count}
    assert [r for r in possessions.player_stats if r["stat_key"] == "Shooting Fouls Drawn"]
    for name in ("opponent_stats", "lineup_stats", "lineup_opponent_stats"):
        assert getattr(possessions, name)


def test_enhanced_loader_is_built_on_the_pbp_loader_as_the_originals_is(tmp_path):
    assert StatsNbaEnhancedPbpLoader.__bases__[0] is StatsNbaPbpLoader
    assert StatsNbaV3EnhancedPbpLoader.__bases__[0] is StatsNbaV3PbpLoader
    directory = str(data_directory(tmp_path, PLAIN))
    loader = StatsNbaV3EnhancedPbpLoader(PLAIN, StatsNbaV3EnhancedPbpFileLoader(directory))
    assert loader.source_data == (DATA / f"stats_v3_{PLAIN}.json").read_bytes()
    assert {row["event_num"] for row in loader.data} == {e.event_num for e in loader.items}
    # The factory gives every class from its row, a team heave's too.
    row = {"action_type": "Heave", "sub_type": "Team Field Goal Attempt"}
    assert StatsNbaV3EnhancedPbpFactory().get_event_class(row) is V3TeamHeave


def test_loaders_read_league_season_and_season_type_as_the_originals_do(tmp_path):
    directory = str(data_directory(tmp_path, PLAIN))
    loaders = (
        StatsNbaV3PbpLoader(PLAIN, StatsNbaV3PbpFileLoader(directory)),
        StatsNbaV3EnhancedPbpLoader(PLAIN, StatsNbaV3EnhancedPbpFileLoader(directory)),
        StatsNbaV3BoxscoreLoader(PLAIN, StatsNbaV3BoxscoreFileLoader(directory)),
    )
    for loader in loaders:
        assert (loader.league, loader.season, loader.season_type) == ("nba", "2025-26", "Regular Season")
    # Playoffs, play-in, the WNBA and the turn of a decade and of the century too.
    for game_id in (PLAIN, "0042400101", "0052400101", "1022600001", "0020900001", "0029900001"):
        original, v3 = StatsNbaLoaderBase(), StatsNbaV3LoaderBase()
        original.game_id = v3.game_id = game_id
        assert (v3.league, v3.season, v3.season_type) == (
            original.league, original.season, original.season_type
        )
