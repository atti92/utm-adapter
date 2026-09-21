from datetime import datetime, timezone

import pytest

from utm_connector.domain import AltitudeDatum, Mission
from utm_connector.mission_reader import MavlinkMissionReader
from utm_connector.missions import MissionParseError


class FakeMessage:
    def __init__(self, message_type: str, *, system_id: int = 1, component_id: int = 1, **fields: object) -> None:
        self._type = message_type
        self._system_id = system_id
        self._component_id = component_id
        for name, value in fields.items():
            setattr(self, name, value)

    def get_type(self) -> str:
        return self._type

    def get_srcSystem(self) -> int:
        return self._system_id

    def get_srcComponent(self) -> int:
        return self._component_id


class FakeMav:
    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[int, ...]]] = []

    def mission_request_list_send(self, system_id: int, component_id: int) -> None:
        self.sent.append(("MISSION_REQUEST_LIST", (system_id, component_id)))

    def mission_request_int_send(self, system_id: int, component_id: int, sequence: int) -> None:
        self.sent.append(("MISSION_REQUEST_INT", (system_id, component_id, sequence)))

    def mission_request_send(self, system_id: int, component_id: int, sequence: int) -> None:
        self.sent.append(("MISSION_REQUEST", (system_id, component_id, sequence)))

    def mission_ack_send(self, system_id: int, component_id: int, ack_type: int) -> None:
        self.sent.append(("MISSION_ACK", (system_id, component_id, ack_type)))


class FakeConnection:
    def __init__(self) -> None:
        self.mav = FakeMav()


class LegacyFakeMav:
    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[int, ...]]] = []

    def mission_request_list_send(self, system_id: int, component_id: int) -> None:
        self.sent.append(("MISSION_REQUEST_LIST", (system_id, component_id)))

    def mission_request_send(self, system_id: int, component_id: int, sequence: int) -> None:
        self.sent.append(("MISSION_REQUEST", (system_id, component_id, sequence)))

    def mission_ack_send(self, system_id: int, component_id: int, ack_type: int) -> None:
        self.sent.append(("MISSION_ACK", (system_id, component_id, ack_type)))


class LegacyFakeConnection:
    def __init__(self) -> None:
        self.mav = LegacyFakeMav()


def _item(sequence: int, *, frame: int = 6, command: int = 16) -> FakeMessage:
    return FakeMessage(
        "MISSION_ITEM_INT",
        seq=sequence,
        frame=frame,
        command=command,
        x=475000000 + sequence * 10000,
        y=190000000 + sequence * 10000,
        z=20 + sequence * 5,
    )


def _legacy_item(sequence: int, *, frame: int = 6, command: int = 16) -> FakeMessage:
    return FakeMessage(
        "MISSION_ITEM",
        seq=sequence,
        frame=frame,
        command=command,
        x=47.5 + sequence * 0.001,
        y=19.0 + sequence * 0.001,
        z=20 + sequence * 5,
    )


def _template() -> Mission:
    return Mission(
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        source="qgroundcontrol",
        waypoints=[
            {"sequence": 0, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 20, "datum": "AGL"}},
            {"sequence": 1, "latitude": 47.501, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
        ],
    )


def test_reader_requests_items_in_order_and_builds_canonical_mission() -> None:
    connection = FakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT"))
    reader.request_list()
    reader.ingest(FakeMessage("MISSION_COUNT", count=2))
    reader.ingest(_item(0))
    completed = reader.ingest(_item(1, command=16), datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert completed is not None
    assert [entry[0] for entry in connection.mav.sent] == [
        "MISSION_REQUEST_LIST",
        "MISSION_REQUEST_INT",
        "MISSION_REQUEST_INT",
        "MISSION_ACK",
    ]
    assert completed.to_mission(_template()).source == "mavlink"
    assert completed.waypoints[1].altitude.datum == AltitudeDatum.AGL


def test_reader_does_not_join_an_unsolicited_gcs_mission_transfer() -> None:
    connection = FakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT"))

    reader.ingest(FakeMessage("MISSION_COUNT", count=2))
    reader.ingest(_item(0))

    assert reader.completed is None
    assert connection.mav.sent == []


def test_reader_rejects_unknown_altitude_frame() -> None:
    connection = FakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT"))
    reader.request_list()
    reader.ingest(FakeMessage("MISSION_COUNT", count=2))

    with pytest.raises(MissionParseError, match="altitude frame"):
        reader.ingest(_item(0, frame=10))


def test_reader_rejects_empty_mission() -> None:
    connection = FakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT"))
    reader.request_list()

    with pytest.raises(MissionParseError, match="empty mission"):
        reader.ingest(FakeMessage("MISSION_COUNT", count=0))


def test_reader_supports_legacy_float_items_and_request_fallback() -> None:
    connection = LegacyFakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT"))
    reader.request_list()
    reader.ingest(FakeMessage("MISSION_COUNT", count=2))
    reader.ingest(_legacy_item(0))
    completed = reader.ingest(
        _legacy_item(1), datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert completed is not None
    assert completed.waypoints[0].latitude == pytest.approx(47.5)
    assert completed.waypoints[1].longitude == pytest.approx(19.001)
    assert [entry[0] for entry in connection.mav.sent] == [
        "MISSION_REQUEST_LIST",
        "MISSION_REQUEST",
        "MISSION_REQUEST",
        "MISSION_ACK",
    ]


def test_reader_ignores_foreign_vehicle_during_mission_transfer() -> None:
    connection = FakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT", system_id=1))
    reader.request_list()
    reader.ingest(FakeMessage("MISSION_COUNT", system_id=1, count=2))
    reader.ingest(FakeMessage("MISSION_COUNT", system_id=2, count=2))
    reader.ingest(_item(0, command=16))
    completed = reader.ingest(_item(1, command=21))

    assert completed is not None
    assert completed.mission_count == 2
    assert [waypoint.latitude for waypoint in completed.waypoints] == [47.5, 47.501]
    assert [entry[0] for entry in connection.mav.sent] == [
        "MISSION_REQUEST_LIST",
        "MISSION_REQUEST_INT",
        "MISSION_REQUEST_INT",
        "MISSION_ACK",
    ]


def test_reader_accepts_a_geographic_landing_item() -> None:
    connection = FakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT"))
    reader.request_list()
    reader.ingest(FakeMessage("MISSION_COUNT", count=2))
    reader.ingest(_item(0))
    completed = reader.ingest(_item(1, command=21))

    assert completed is not None
    assert completed.waypoints[1].latitude == pytest.approx(47.501)


def test_reader_ignores_a_final_return_to_launch_item() -> None:
    connection = FakeConnection()
    reader = MavlinkMissionReader("sitl-1", connection)
    reader.ingest(FakeMessage("HEARTBEAT"))
    reader.request_list()
    reader.ingest(FakeMessage("MISSION_COUNT", count=3))
    reader.ingest(_item(0))
    reader.ingest(_item(1))
    completed = reader.ingest(_item(2, command=20), datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert completed is not None
    assert completed.mission_count == 3
    assert len(completed.waypoints) == 2
    assert [waypoint.sequence for waypoint in completed.waypoints] == [0, 1]
