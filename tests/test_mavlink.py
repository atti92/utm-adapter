from datetime import datetime, timedelta, timezone

import pytest

from utm_connector.domain import TelemetryQuality, VehicleConnectionState
from utm_connector.mavlink import MavlinkMessageNormalizer, MavlinkVehicleSession


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
