import json
import socket
import sys
from copy import deepcopy
from decimal import Decimal, localcontext

import pytest
from v3_fixtures import DATA, manifest_fixtures

from pbpstats.client import DATA_LOADER_SUFFIX, DATA_SOURCE_SUFFIX, Client
from pbpstats.data_loader.factory import DataLoaderFactory
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.data_loader.stats_nba_v3.pbp.loader import V3PbpSourceData
from pbpstats.objects.game import Game
from pbpstats.resources.pbp.pbp import Pbp

GAME_ID = "0021900001"
FIXTURES = manifest_fixtures()


class RecordedSource:
    def __init__(self, payload, source_bytes=None):
        self.payload = payload
        self.source_bytes = source_bytes

    def load_data(self, game_id):
        return V3PbpSourceData(payload=self.payload, source_bytes=self.source_bytes)


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("File ingestion attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def payload():
    data = json.loads((DATA / f"pbp/stats_v3_{GAME_ID}.json").read_bytes())
    data["game"]["actions"] = data["game"]["actions"][:1]
    return data


def load_payload(payload):
    return StatsNbaV3PbpLoader(GAME_ID, RecordedSource(payload))


def write_file(directory, raw, game_id=GAME_ID):
    path = directory / "pbp" / f"stats_v3_{game_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["game_id"])
def test_loads_recorded_rows_without_changes(fixture, tmp_path):
    raw = (DATA / fixture["path"]).read_bytes()
    path = write_file(tmp_path, raw, fixture["game_id"])
    source = StatsNbaV3PbpFileLoader(tmp_path)
    loader = StatsNbaV3PbpLoader(fixture["game_id"], source)
    expected = json.loads(raw)
    assert loader.game_id == fixture["game_id"]
    assert loader.source_data == expected
    assert loader.source_bytes == raw
    assert loader.data == expected["game"]["actions"]
    assert Pbp(loader.items).data == loader.data
    assert len(loader.items) == fixture["actions"]
    # Compare positionally against the source: an order assertion built from
    # enumerate() would hold even if the loader had reordered the actions.
    assert [item.action_number for item in loader.items] == [
        action["actionNumber"] for action in expected["game"]["actions"]
    ]
    assert [item.order for item in loader.items] == list(range(fixture["actions"]))
    for item, event in zip(loader.items, expected["game"]["actions"]):
        assert item.game_id == fixture["game_id"]
        assert item.action_id == event["actionId"]
        assert item.action_number == event["actionNumber"]
        assert item.action_type == event["actionType"]
        assert item.sub_type == event["subType"]
        assert item.period == event["period"]
        assert item.clock == event["clock"]
    assert path.read_bytes() == raw


def test_preserves_split_actions_source_order_and_fractional_clock():
    loader = StatsNbaV3PbpLoader(GAME_ID, StatsNbaV3PbpFileLoader(DATA))
    assert len(loader.items) == 596
    assert len({item.action_number for item in loader.items}) == 573
    assert sum(item.action_type == "" for item in loader.items) == 23
    assert [
        item.action_number
        for item in loader.items
        if item.action_number in (170, 171, 172)
    ] == [170, 172, 171]
    item = next(item for item in loader.items if item.action_number == 184)
    assert item.clock == "PT00M02.80S"
    assert item.seconds_remaining == 2.8
    assert isinstance(item.seconds_remaining, float)
    # str(), not ==: Decimal("2.8") == Decimal("2.80") is True, so equality
    # alone cannot show that the recorded scale survived.
    assert str(item.seconds_remaining_exact) == "2.80"


# Counted from the recorded fixtures. A change here means the snapshot was
# re-recorded: confirm the new provenance rather than editing to make it pass.
FIXTURE_CONTENT = {
    "0021900001": {
        "periods": [1, 2, 3, 4, 5],
        "blank_action_types": 23,
        "repeated_action_numbers": 23,
        "backward_steps": [(129, 172, 171), (153, 282, 196)],
    },
    "0022400001": {
        "periods": [1, 2, 3, 4],
        "blank_action_types": 30,
        "repeated_action_numbers": 30,
        "backward_steps": [],
    },
    "0042500317": {
        "periods": [1, 3],
        "blank_action_types": 0,
        "repeated_action_numbers": 0,
        "backward_steps": [],
    },
}


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["game_id"])
def test_each_fixture_keeps_its_own_distinguishing_content(fixture, tmp_path):
    """Round-trip equality cannot see content, so pin what each snapshot is for.

    0022400001 is the only published, provenance-verified fixture and the only
    one without overtime; the heaves excerpt is the only non-contiguous one.
    """
    expected = FIXTURE_CONTENT[fixture["game_id"]]
    write_file(tmp_path, (DATA / fixture["path"]).read_bytes(), fixture["game_id"])
    items = StatsNbaV3PbpLoader(
        fixture["game_id"], StatsNbaV3PbpFileLoader(tmp_path)
    ).items
    numbers = [item.action_number for item in items]
    assert sorted({item.period for item in items}) == expected["periods"]
    assert sum(item.action_type == "" for item in items) == (
        expected["blank_action_types"]
    )
    assert len(numbers) - len(set(numbers)) == expected["repeated_action_numbers"]
    # Every place the feed steps backwards, not just the first one.
    assert [
        (index, numbers[index - 1], numbers[index])
        for index in range(1, len(numbers))
        if numbers[index] < numbers[index - 1]
    ] == [tuple(step) for step in expected["backward_steps"]]
    assert all(item.description == item.get("description") for item in items)


def test_excerpt_is_a_gapped_selection_not_a_prefix(tmp_path):
    """The excerpt's point is non-contiguous rows; a prefix would not test that."""
    excerpt = next(f for f in FIXTURES if f["game_id"] == "0042500317")
    write_file(tmp_path, (DATA / excerpt["path"]).read_bytes(), "0042500317")
    loader = StatsNbaV3PbpLoader("0042500317", StatsNbaV3PbpFileLoader(tmp_path))
    assert [item.action_number for item in loader.items] == [
        161,
        162,
        163,
        164,
        540,
        541,
        542,
        543,
    ]
    assert [item.order for item in loader.items] == list(range(8))


def test_identical_rows_and_repeated_ids_are_not_deduplicated(payload):
    row = payload["game"]["actions"][0]
    payload["game"]["actions"].append(deepcopy(row))
    items = load_payload(payload).items
    assert len(items) == 2
    assert items[0].data == items[1].data == row
    assert [item.order for item in items] == [0, 1]


def test_unknown_fields_and_types_cannot_overwrite_metadata(payload):
    payload["futureEnvelope"] = {"values": [1, None, True]}
    payload["game"]["futureGame"] = "preserved"
    event = payload["game"]["actions"][0]
    event.update(
        {
            "actionType": "Future Action",
            "subType": "",
            "data": {"x": [1]},
            "order": 999,
            "game_id": "source-field",
            "seconds_remaining": "source-field",
        }
    )
    expected = deepcopy(payload)
    loader = load_payload(payload)
    item = loader.items[0]
    assert item.action_type == "Future Action"
    assert item.description == event["description"]
    assert item.get("data") == {"x": [1]}
    assert item.get("nothingHere", "fallback") == "fallback"
    # get() must not hand back stored state through a container
    item.get("data")["x"].append(2)
    assert item.get("data") == {"x": [1]}
    assert item.order == 0
    assert item.game_id == GAME_ID
    assert isinstance(item.seconds_remaining, float)
    assert isinstance(item.seconds_remaining_exact, Decimal)
    assert item.data == event
    with pytest.raises(AttributeError):
        item.order = 2

    payload["game"]["actions"].clear()
    loader.source_data["futureEnvelope"]["values"].append(2)
    loader.data[0]["data"]["x"].append(2)
    item.data["data"]["x"].append(2)
    assert loader.source_data == expected
    assert item.data == expected["game"]["actions"][0]


def test_empty_feed_is_preserved_without_claiming_completion(payload):
    payload["game"]["actions"] = []
    loader = load_payload(payload)
    assert loader.items == []
    assert loader.data == []
    assert loader.source_data == payload


def test_file_source_reuse_does_not_change_earlier_loader():
    source = StatsNbaV3PbpFileLoader(DATA)
    first = StatsNbaV3PbpLoader(GAME_ID, source)
    second = StatsNbaV3PbpLoader("0022400001", source)
    assert first.source_bytes == (DATA / f"pbp/stats_v3_{GAME_ID}.json").read_bytes()
    assert first.source_data["game"]["gameId"] == GAME_ID
    assert second.source_data["game"]["gameId"] == "0022400001"
    assert second.source_bytes != first.source_bytes
    with pytest.raises(FileNotFoundError):
        source.load_data("0029900001")
    assert first.source_bytes is not None


def test_source_keeps_no_per_game_state_between_loads():
    """Bytes come back with the payload, so a reused source cannot mix them up."""
    source = StatsNbaV3PbpFileLoader(DATA)
    assert not hasattr(source, "source_bytes")
    for game_id in (GAME_ID, "0022400001"):
        result = source.load_data(game_id)
        assert result.payload["game"]["gameId"] == game_id
        expected = (DATA / f"pbp/stats_v3_{game_id}.json").read_bytes()
        assert result.source_bytes == expected


@pytest.mark.parametrize(
    "payload_override, match",
    [
        ({"gameId": "0022400001"}, "game.gameId"),
        ({"actions": "nope"}, "game.actions must be an array"),
    ],
)
def test_rejected_payload_leaves_no_bytes_behind(tmp_path, payload_override, match):
    """A file rejected by the envelope check must not look like a loaded one."""
    game = {"gameId": GAME_ID, "actions": []}
    game.update(payload_override)
    raw = json.dumps({"game": game}).encode("utf-8")
    write_file(tmp_path, raw)
    source = StatsNbaV3PbpFileLoader(tmp_path)
    with pytest.raises(ValueError, match=match):
        StatsNbaV3PbpLoader(GAME_ID, source)
    assert not hasattr(source, "source_bytes")


def test_source_returning_a_bare_payload_is_rejected(payload):
    """A source that does not follow the protocol fails loudly, not silently."""

    class BarePayloadSource:
        def load_data(self, game_id):
            return payload

    with pytest.raises(TypeError, match="must return V3PbpSourceData"):
        StatsNbaV3PbpLoader(GAME_ID, BarePayloadSource())


def test_loader_does_not_keep_an_unused_file_directory(payload):
    assert not hasattr(load_payload(payload), "file_directory")


@pytest.mark.parametrize(
    "game_id",
    [
        None,
        21900001,
        True,
        "21900001",
        "../../file",
        "0021900001/",
        "3021900001",
        "00１９０００００１",
    ],
)
def test_invalid_game_id_is_rejected_before_source_access(game_id):
    class UnreadableSource:
        def load_data(self, game_id):
            pytest.fail("Invalid game ID reached the source")

    with pytest.raises(ValueError, match="10-digit NBA"):
        StatsNbaV3PbpLoader(game_id, UnreadableSource())


def test_file_source_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="game_id"):
        StatsNbaV3PbpFileLoader(tmp_path).load_data("../../file")


@pytest.mark.parametrize("value", [None, [], "response"])
def test_invalid_root(value):
    with pytest.raises(ValueError, match=f"{GAME_ID}: response must be an object"):
        load_payload(value)


@pytest.mark.parametrize("value", [None, [], "game"])
def test_invalid_game_object(payload, value):
    payload["game"] = value
    with pytest.raises(ValueError, match="game must be an object"):
        load_payload(payload)


@pytest.mark.parametrize("value", [None, 21900001, "0022400001"])
def test_payload_game_id_must_match_request(payload, value):
    payload["game"]["gameId"] = value
    with pytest.raises(ValueError, match=f"{GAME_ID}: game.gameId"):
        load_payload(payload)


@pytest.mark.parametrize("value", [None, {}, "actions"])
def test_actions_must_be_an_array(payload, value):
    payload["game"]["actions"] = value
    with pytest.raises(ValueError, match="game.actions must be an array"):
        load_payload(payload)


@pytest.mark.parametrize("value", [None, [], "action", 12])
def test_invalid_action_reports_source_index(payload, value):
    payload["game"]["actions"].append(value)
    with pytest.raises(
        ValueError, match=rf"{GAME_ID}, game.actions\[1\]: action must be an object"
    ):
        load_payload(payload)


@pytest.mark.parametrize(
    "field, value",
    [
        ("actionId", None),
        ("actionId", True),
        ("actionId", -1),
        ("actionNumber", "1"),
        ("actionNumber", False),
        ("actionNumber", -1),
        ("period", None),
        ("period", 0),
        ("period", True),
        ("period", 1.5),
        ("actionType", None),
        ("subType", None),
        ("description", []),
        ("clock", 720),
    ],
)
def test_invalid_core_fields_report_source_index(payload, field, value):
    payload["game"]["actions"][0][field] = value
    with pytest.raises(ValueError, match=rf"{GAME_ID}, game.actions\[0\].{field}"):
        load_payload(payload)


@pytest.mark.parametrize(
    "field",
    [
        "actionId",
        "actionNumber",
        "period",
        "clock",
        "actionType",
        "subType",
        "description",
    ],
)
def test_missing_core_fields(payload, field):
    del payload["game"]["actions"][0][field]
    with pytest.raises(ValueError, match=rf"game.actions\[0\].{field}"):
        load_payload(payload)


@pytest.mark.parametrize(
    "clock, period, expected",
    [
        ("PT12M00.00S", 1, "720.00"),
        ("PT01M02.80S", 2, "62.80"),
        ("PT00M02.80S", 4, "2.80"),
        ("PT05M00.00S", 5, "300.00"),
        ("PT00M00.00S", 7, "0.00"),
        (
            "PT01M02.123456789012345678901234567890123S",
            1,
            "62.123456789012345678901234567890123",
        ),
    ],
)
def test_clocks_retain_precision_independent_of_decimal_context(
    payload, clock, period, expected
):
    payload["game"]["actions"][0].update(clock=clock, period=period)
    with localcontext() as context:
        context.prec = 2
        item = load_payload(payload).items[0]
    # Compare the string: Decimal("7.2E+2") == Decimal("720.00") is True, so
    # equality alone passes even when the caller's precision has been applied.
    assert str(item.seconds_remaining_exact) == expected
    assert item.clock == clock


@pytest.mark.parametrize(
    "clock, period",
    [
        ("0:02", 1),
        ("", 1),
        ("PT00M-1S", 1),
        ("PT00MNaNS", 1),
        ("PT00MInfinityS", 1),
        ("PT00M60S", 1),
        ("PT13M00S", 1),
        ("PT12M00.01S", 4),
        ("PT05M00.01S", 5),
        (" PT00M01S", 1),
    ],
)
def test_invalid_clocks(payload, clock, period):
    payload["game"]["actions"][0].update(clock=clock, period=period)
    with pytest.raises(ValueError, match=r"game.actions\[0\].clock"):
        load_payload(payload)


@pytest.mark.parametrize(
    "raw, reason",
    [
        (b"{", "Expecting"),
        (b"\xff", "decode"),
        (b'{"game": {}, "game": {}}', "duplicate JSON key"),
        (b'{"meta": {"x": 1, "x": 2}}', "duplicate JSON key"),
        (b'{"meta": NaN}', "non-finite JSON number"),
        (b'{"meta": Infinity}', "non-finite JSON number"),
        (b'{"meta": -Infinity}', "non-finite JSON number"),
        (b'{"meta": 1e999}', "supported float range"),
    ],
)
def test_malformed_json_reports_game_and_file(tmp_path, raw, reason):
    path = write_file(tmp_path, raw)
    source = StatsNbaV3PbpFileLoader(tmp_path)
    with pytest.raises(ValueError, match=reason) as error:
        StatsNbaV3PbpLoader(GAME_ID, source)
    assert GAME_ID in str(error.value)
    assert str(path) in str(error.value)
    assert path.read_bytes() == raw


def test_decoder_recursion_error_reports_game_and_file(payload, tmp_path, monkeypatch):
    raw = json.dumps(payload).encode("utf-8")
    path = write_file(tmp_path, raw)
    source = StatsNbaV3PbpFileLoader(tmp_path)

    def exceed_decoder_limit(*args, **kwargs):
        raise RecursionError("decoder recursion limit exceeded")

    # Decoder nesting limits vary across supported Python versions.
    with monkeypatch.context() as patch:
        patch.setattr(
            "pbpstats.data_loader.stats_nba_v3.pbp.file.json.loads",
            exceed_decoder_limit,
        )
        with pytest.raises(ValueError, match="decoder recursion limit") as error:
            StatsNbaV3PbpLoader(GAME_ID, source)
    assert GAME_ID in str(error.value)
    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, RecursionError)
    assert path.read_bytes() == raw


def test_deeply_nested_decoded_payload_reports_game(payload):
    nested = []
    for _ in range(sys.getrecursionlimit() + 10):
        nested = [nested]
    payload["meta"] = nested
    with pytest.raises(ValueError, match="response nests too deeply to copy") as error:
        load_payload(payload)
    assert GAME_ID in str(error.value)
    assert isinstance(error.value.__cause__, RecursionError)


def test_utf8_bom_and_non_ascii_text_preserve_original_bytes(payload, tmp_path):
    payload["game"]["actions"][0]["description"] = "Jokić — 試合"
    raw = b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8")
    write_file(tmp_path, raw)
    loader = StatsNbaV3PbpLoader(GAME_ID, StatsNbaV3PbpFileLoader(tmp_path))
    assert loader.source_bytes == raw
    assert loader.source_data == payload


def test_missing_v3_file_never_falls_back_to_v2(tmp_path):
    (tmp_path / "pbp").mkdir()
    (tmp_path / "pbp" / f"stats_{GAME_ID}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match=f"stats_v3_{GAME_ID}"):
        StatsNbaV3PbpLoader(GAME_ID, StatsNbaV3PbpFileLoader(tmp_path))


@pytest.mark.parametrize("file_directory", [None, "", "   "])
def test_file_directory_is_required(file_directory):
    """A blank directory would otherwise resolve to the working directory."""
    with pytest.raises(ValueError, match="file_directory cannot be None"):
        StatsNbaV3PbpFileLoader(file_directory)


def test_factory_registers_v3_without_disturbing_existing_providers():
    factory = DataLoaderFactory()
    for provider in ("stats_nba", "data_nba", "live"):
        loaders = factory.get_data_loader(provider, "Pbp")
        assert len(loaders) == 1
        assert loaders[0]["file_source"] is not None
        assert loaders[0]["web_source"] is not None
    v3 = factory.get_data_loader("stats_nba_v3", "Pbp")
    assert len(v3) == 1
    assert v3[0]["loader"] is StatsNbaV3PbpLoader
    assert v3[0]["file_source"] is StatsNbaV3PbpFileLoader
    assert v3[0]["web_source"] is None


@pytest.fixture
def restore_game_class():
    """Isolate the shared Game class that Client configures.

    Client sets ``*DataLoaderClass``/``*DataSource`` attributes on the Game
    class itself, and Game.__init__ loads every resource it finds there. So
    clear what earlier tests left behind, then put it all back.
    """
    suffixes = (DATA_LOADER_SUFFIX, DATA_SOURCE_SUFFIX)
    before = dict(Game.__dict__)
    for name in list(Game.__dict__):
        if name.endswith(suffixes):
            delattr(Game, name)
    yield
    for name in set(Game.__dict__) - set(before):
        if not name.startswith("__"):
            delattr(Game, name)
    for name, value in before.items():
        if name.startswith("__"):
            continue
        if getattr(Game, name, object()) is not value:
            setattr(Game, name, value)


def test_client_loads_v3_from_file(restore_game_class):
    client = Client(
        {"dir": str(DATA), "Pbp": {"source": "file", "data_provider": "stats_nba_v3"}}
    )
    game = client.Game(GAME_ID)
    assert len(game.pbp.items) == 596


def test_client_names_the_missing_web_source(restore_game_class):
    """Selecting a source the provider lacks says so instead of failing later."""
    with pytest.raises(ValueError, match="stats_nba_v3 has no web source"):
        Client(
            {
                "dir": str(DATA),
                "Pbp": {"source": "web", "data_provider": "stats_nba_v3"},
            }
        )


@pytest.mark.parametrize("configure_boxscore_first", [False, True])
def test_rejected_client_preserves_existing_client(
    restore_game_class, tmp_path, configure_boxscore_first
):
    client = Client(
        {"dir": str(DATA), "Pbp": {"source": "file", "data_provider": "stats_nba"}}
    )
    original = client.Game(GAME_ID).pbp.data
    before = dict(client.Game.__dict__)
    settings = {"dir": str(tmp_path)}
    if configure_boxscore_first:
        settings["Boxscore"] = {"source": "file", "data_provider": "live"}
    settings["Pbp"] = {"source": "web", "data_provider": "stats_nba_v3"}

    with pytest.raises(ValueError, match="stats_nba_v3 has no web source"):
        Client(settings)

    assert dict(client.Game.__dict__) == before
    assert client.Game(GAME_ID).pbp.data == original
