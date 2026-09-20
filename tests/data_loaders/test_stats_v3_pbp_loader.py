import json
import socket
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from pbpstats.data_loader.factory import DataLoaderFactory
from pbpstats.data_loader.stats_nba_v3.pbp import (
    StatsNbaV3PbpFileLoader,
    StatsNbaV3PbpLoader,
)
from pbpstats.resources.pbp.pbp import Pbp

DATA = Path(__file__).resolve().parents[1] / "data"
GAME_ID = "0021900001"
FIXTURES = json.loads((DATA / "v3/manifest.json").read_text(encoding="utf-8"))[
    "fixtures"
]


class RecordedSource:
    def __init__(self, payload):
        self.payload = payload

    def load_data(self, game_id):
        return self.payload


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
    assert item.seconds_remaining == Decimal("2.80")
    assert item.clock == "PT00M02.80S"


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
    assert item.order == 0
    assert item.game_id == GAME_ID
    assert isinstance(item.seconds_remaining, Decimal)
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
    with pytest.raises(FileNotFoundError):
        source.load_data("0029900001")
    assert source.source_bytes is None
    assert first.source_bytes is not None


@pytest.mark.parametrize(
    "game_id",
    [
        None,
        21900001,
        True,
        "21900001",
        "../../file",
        "0021900001/",
        "1021900001",
        "00１９０００００１",
    ],
)
def test_invalid_game_id_is_rejected_before_source_access(game_id):
    class UnreadableSource:
        def load_data(self, game_id):
            pytest.fail("Invalid game ID reached the source")

    with pytest.raises(ValueError, match="10-digit NBA string"):
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
    assert item.seconds_remaining == Decimal(expected)
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
    assert source.source_bytes is None
    assert path.read_bytes() == raw


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


def test_file_directory_is_required():
    with pytest.raises(ValueError, match="file_directory cannot be None"):
        StatsNbaV3PbpFileLoader(None)


def test_direct_v3_imports_leave_existing_factory_registrations_intact():
    factory = DataLoaderFactory()
    for provider in ("stats_nba", "data_nba", "live"):
        loaders = factory.get_data_loader(provider, "Pbp")
        assert len(loaders) == 1
        assert loaders[0]["file_source"] is not None
        assert loaders[0]["web_source"] is not None
