from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from utm_connector.domain import TelemetryQuality, VehicleConnectionState
from utm_connector.mavlink import MavlinkMessageNormalizer, MavlinkVehicleSession
from utm_connector.recording import JsonlRecorder, JsonlReplay


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


class FakeConnection:
    def __init__(self) -> None:
        self.mav = object()


class PollingConnection(FakeConnection):
    def __init__(self, message: FakeMessage) -> None:
        super().__init__()
        self.stream_requests = []
        self.mission_requests = []
        self.mav = SimpleNamespace(
            mission_request_list_send=lambda *args: self.mission_requests.append(args),
            request_data_stream_send=lambda *args: self.stream_requests.append(args),
        )
        self.message = message
        self.closed = False

    def recv_match(self, *, blocking: bool, timeout: float | None) -> FakeMessage:
        return self.message

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("connection_uri", "expected_device", "expected_baud"),
    (
        ("serial:/dev/ttyUSB0:57600", "/dev/ttyUSB0", 57600),
        ("serial:///dev/ttyUSB0:115200", "/dev/ttyUSB0", 115200),
        ("serial:COM3:57600", "COM3", 57600),
        ("serial:COM3", "COM3", 115200),
    ),
)
def test_connect_supports_explicit_cross_platform_serial_uri(
    monkeypatch: pytest.MonkeyPatch,
    connection_uri: str,
    expected_device: str,
    expected_baud: int,
) -> None:
    calls = []
    connection = FakeConnection()

    def fake_connection(device: str, **kwargs: object) -> FakeConnection:
        calls.append((device, kwargs))
        return connection

    monkeypatch.setattr("utm_connector.mavlink.mavutil.mavlink_connection", fake_connection)
    session = MavlinkVehicleSession.connect("sitl-1", connection_uri)

    assert session.connection is connection
    assert calls == [(expected_device, {"baud": expected_baud})]


def test_connect_passes_non_serial_uri_through_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    connection = FakeConnection()

    def fake_connection(uri: str, **kwargs: object) -> FakeConnection:
        calls.append((uri, kwargs))
        return connection

    monkeypatch.setattr("utm_connector.mavlink.mavutil.mavlink_connection", fake_connection)
    MavlinkVehicleSession.connect("sitl-1", "udpin:127.0.0.1:14551")

    assert calls == [("udpin:127.0.0.1:14551", {})]


def test_connect_rejects_serial_uri_without_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("utm_connector.mavlink.mavutil.mavlink_connection", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="device path"):
        MavlinkVehicleSession.connect("sitl-1", "serial::57600")


def test_mavlink_messages_become_one_canonical_snapshot() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    normalizer = MavlinkMessageNormalizer("sitl-1")
    normalizer.ingest(FakeMessage("HEARTBEAT", autopilot=3, type=2, base_mode=128), now)
    normalizer.ingest(FakeMessage("GPS_RAW_INT", fix_type=3, satellites_visible=12), now)
    normalizer.ingest(
        FakeMessage(
            "GLOBAL_POSITION_INT",
            lat=475000000,
            lon=190000000,
            alt=12345,
            hdg=9000,
        ),
        now,
    )
    normalizer.ingest(FakeMessage("VFR_HUD", heading=91, groundspeed=5.5), now)
    normalizer.ingest(FakeMessage("BATTERY_STATUS", battery_remaining=80, voltages=[12000, 65535]), now)
    normalizer.ingest(FakeMessage("MISSION_COUNT", count=4), now)
    normalizer.ingest(FakeMessage("MISSION_CURRENT", seq=2), now)
    normalizer.ingest(FakeMessage("STATUSTEXT", text="Ready"), now)

    snapshot = normalizer.snapshot(now)
    assert snapshot.identity.connector_vehicle_id == "sitl-1"
    assert snapshot.identity.mavlink_system_id == 1
    assert snapshot.identity.mavlink_component_ids == [1]
    assert snapshot.connection_state == VehicleConnectionState.CONNECTED
    assert snapshot.quality == TelemetryQuality.GOOD
    assert snapshot.telemetry is not None
    assert snapshot.telemetry.latitude == 47.5
    assert snapshot.telemetry.altitude.meters == 12.345
    assert snapshot.telemetry.altitude.datum == "AMSL"
    assert snapshot.telemetry.heading_deg == 91
    assert snapshot.telemetry.groundspeed_mps == 5.5
    assert snapshot.health.battery_voltage_v == 12
    assert snapshot.health.battery_remaining_pct == 80
    assert snapshot.mission_current == 2
    assert snapshot.mission_count == 4
    assert snapshot.diagnostics == ["Ready"]


def test_telemetry_transitions_to_lost_without_heartbeat() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    normalizer = MavlinkMessageNormalizer("sitl-1")
    normalizer.ingest(FakeMessage("HEARTBEAT", autopilot=3, type=2, base_mode=0), now)
    normalizer.ingest(FakeMessage("GLOBAL_POSITION_INT", lat=0, lon=0, alt=0, hdg=0), now)

    snapshot = normalizer.snapshot(now + timedelta(seconds=11))
    assert snapshot.connection_state == VehicleConnectionState.LOST
    assert snapshot.quality == TelemetryQuality.LOST
    assert snapshot.health.heartbeat_age_s == 11


def test_gcs_heartbeat_cannot_replace_vehicle_identity() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    normalizer = MavlinkMessageNormalizer("sitl-1")
    normalizer.ingest(FakeMessage("HEARTBEAT", system_id=1, component_id=1, autopilot=3, type=2), now)
    normalizer.ingest(
        FakeMessage("HEARTBEAT", system_id=255, component_id=190, autopilot=8, type=6),
        now + timedelta(seconds=1),
    )

    snapshot = normalizer.snapshot(now + timedelta(seconds=1))
    assert snapshot.identity.mavlink_system_id == 1
    assert snapshot.identity.mavlink_component_ids == [1]
    assert snapshot.identity.autopilot_type == "3"


def test_message_timestamps_must_be_timezone_aware() -> None:
    normalizer = MavlinkMessageNormalizer("sitl-1")
    with pytest.raises(ValueError, match="timezone"):
        normalizer.ingest(FakeMessage("HEARTBEAT"), datetime(2026, 1, 1, 12, 0))


def test_heading_sentinels_are_normalized_to_unknown() -> None:
    assert MavlinkMessageNormalizer._heading(65535) is None
    assert MavlinkMessageNormalizer._heading(36000) is None
    assert MavlinkMessageNormalizer._heading(9000) == 90


def test_empty_onboard_mission_does_not_interrupt_telemetry() -> None:
    session = MavlinkVehicleSession("sitl-1", FakeConnection())
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    session.ingest(FakeMessage("HEARTBEAT"), now)
    session.ingest(FakeMessage("MISSION_COUNT", count=0), now)

    snapshot = session.snapshot(now)
    assert snapshot.connection_state == VehicleConnectionState.CONNECTED
    assert snapshot.mission_count == 0
    assert snapshot.diagnostics == [
        "MAVLink mission unavailable: MAVLink vehicle reported an empty mission"
    ]


def test_session_records_raw_wire_frame_without_changing_telemetry(tmp_path) -> None:
    message = FakeMessage("STATUSTEXT", text="Ready")
    message.get_msgbuf = lambda: b"\xfe\x01\x02"
    connection = PollingConnection(message)
    recorder = JsonlRecorder(str(tmp_path / "events.jsonl"))
    session = MavlinkVehicleSession("sitl-1", connection, recorder=recorder)

    assert session.poll() is message
    session.close()
    recorder.close()

    frames = list(JsonlReplay(str(tmp_path / "events.jsonl")).mavlink_frames())
    assert frames == [("sitl-1", b"\xfe\x01\x02")]
    assert connection.closed is True


def test_session_requests_read_only_telemetry_streams_once_after_heartbeat() -> None:
    message = FakeMessage("HEARTBEAT", autopilot=3, type=2, base_mode=0)
    connection = PollingConnection(message)
    session = MavlinkVehicleSession("sitl-1", connection)

    session.poll()
    session.poll()

    assert len(connection.stream_requests) == 4
    assert all(request[0:2] == (1, 1) for request in connection.stream_requests)
    assert all(request[3:] == (4, 1) for request in connection.stream_requests)


def test_session_does_not_request_onboard_mission_until_explicitly_requested() -> None:
    message = FakeMessage("HEARTBEAT", autopilot=3, type=2, base_mode=0)
    connection = PollingConnection(message)
    session = MavlinkVehicleSession("sitl-1", connection)

    session.poll()
    session.poll()
    assert connection.mission_requests == []

    session.request_mission()
    assert connection.mission_requests == [(1, 1)]


def test_sys_status_supplies_battery_fallback_when_battery_status_is_absent() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    normalizer = MavlinkMessageNormalizer("sitl-1")

    normalizer.ingest(FakeMessage("HEARTBEAT", autopilot=3, type=2), now)
    normalizer.ingest(
        FakeMessage("SYS_STATUS", battery_remaining=72, voltage_battery=11800),
        now,
    )

    health = normalizer.snapshot(now).health
    assert health.battery_remaining_pct == 72
    assert health.battery_voltage_v == 11.8
