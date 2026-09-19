"""Read-only MAVLink ingestion and normalization.

The rest of the connector only sees canonical models from this module.  It does
not depend on pymavlink message classes or MAVLink dialect details.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Callable, Optional

from pymavlink import mavutil

from .domain import (
    Altitude,
    AltitudeDatum,
    TelemetryQuality,
    VehicleConnectionState,
    VehicleHealth,
    VehicleIdentity,
    VehicleStateSnapshot,
    VehicleTelemetry,
)
from .mission_reader import MavlinkMissionRead, MavlinkMissionReader
from .missions import MissionParseError
from .recording import JsonlRecorder


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _message_type(message: Any) -> str:
    getter = getattr(message, "get_type", None)
    return getter() if callable(getter) else str(getattr(message, "_type", "UNKNOWN"))


def _source_id(message: Any, name: str, default: int = 0) -> int:
    getter = getattr(message, name, None)
    if callable(getter):
        return int(getter())
    return int(getattr(message, name.replace("get_", ""), default))


class MavlinkMessageNormalizer:
    """Convert selected MAVLink messages into one coherent vehicle snapshot."""

    def __init__(
        self,
        vehicle_id: str,
        *,
        stale_after_s: float = 3.0,
        lost_after_s: float = 10.0,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if stale_after_s <= 0 or lost_after_s <= stale_after_s:
            raise ValueError("lost_after_s must be greater than stale_after_s, both above zero")
        self.vehicle_id = vehicle_id
        self.stale_after_s = stale_after_s
        self.lost_after_s = lost_after_s
        self.clock = clock
        self._system_id: Optional[int] = None
        self._component_ids = set()
        self._autopilot_type: Optional[str] = None
        self._vehicle_type: Optional[str] = None
        self._firmware_version: Optional[str] = None
        self._last_heartbeat_at: Optional[datetime] = None
        self._last_position_at: Optional[datetime] = None
        self._last_telemetry: Optional[VehicleTelemetry] = None
        self._gps_fix_type: Optional[int] = None
        self._satellites_visible: Optional[int] = None
        self._battery_remaining_pct: Optional[float] = None
        self._battery_voltage_v: Optional[float] = None
        self._armed: Optional[bool] = None
        self._mission_current: Optional[int] = None
        self._mission_count: Optional[int] = None
        self._diagnostics = []

    def ingest(self, message: Any, received_at: Optional[datetime] = None) -> None:
        received_at = received_at or self.clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        received_at = received_at.astimezone(timezone.utc)
        message_type = _message_type(message)
        system_id = _source_id(message, "get_srcSystem")
        component_id = _source_id(message, "get_srcComponent")
        if system_id:
            self._system_id = system_id
        if component_id:
            self._component_ids.add(component_id)

        if message_type == "HEARTBEAT":
            self._last_heartbeat_at = received_at
            self._autopilot_type = str(getattr(message, "autopilot", "UNKNOWN"))
            self._vehicle_type = str(getattr(message, "type", "UNKNOWN"))
            base_mode = int(getattr(message, "base_mode", 0))
            self._armed = bool(base_mode & int(mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED))
        elif message_type == "GLOBAL_POSITION_INT":
            self._last_position_at = received_at
            self._last_telemetry = VehicleTelemetry(
                vehicle_id=self.vehicle_id,
                observed_at=received_at,
                latitude=float(message.lat) / 10_000_000,
                longitude=float(message.lon) / 10_000_000,
                # GLOBAL_POSITION_INT.alt is millimetres above mean sea level.
                altitude=Altitude(meters=float(message.alt) / 1000, datum=AltitudeDatum.AMSL),
                heading_deg=self._heading(getattr(message, "hdg", None)),
                groundspeed_mps=self._last_telemetry.groundspeed_mps if self._last_telemetry else None,
                quality=self._quality(received_at),
            )
        elif message_type == "GPS_RAW_INT":
            self._gps_fix_type = int(getattr(message, "fix_type", 0))
            satellites = int(getattr(message, "satellites_visible", 0))
            self._satellites_visible = satellites if satellites >= 0 else None
        elif message_type == "VFR_HUD":
            if self._last_telemetry:
                self._last_telemetry = self._last_telemetry.model_copy(
                    update={
                        "heading_deg": self._heading(getattr(message, "heading", None)),
                        "groundspeed_mps": max(0.0, float(getattr(message, "groundspeed", 0))),
                    }
                )
        elif message_type == "BATTERY_STATUS":
            remaining = int(getattr(message, "battery_remaining", -1))
            voltage = self._first_battery_voltage(getattr(message, "voltages", []))
            self._battery_remaining_pct = float(remaining) if 0 <= remaining <= 100 else None
            self._battery_voltage_v = voltage
        elif message_type == "MISSION_CURRENT":
            sequence = int(getattr(message, "seq", 0))
            self._mission_current = sequence if sequence >= 0 else None
        elif message_type == "MISSION_COUNT":
            count = int(getattr(message, "count", 0))
            self._mission_count = count if count >= 0 else None
        elif message_type == "AUTOPILOT_VERSION":
            version = int(getattr(message, "flight_sw_version", 0))
            self._firmware_version = str(version) if version else None
        elif message_type == "STATUSTEXT":
            text = getattr(message, "text", "")
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            if text:
                self._add_diagnostic(str(text).rstrip("\x00"))

        self._refresh_quality(received_at)

    @staticmethod
    def _first_battery_voltage(voltages: Any) -> Optional[float]:
        for millivolts in voltages or []:
            value = int(millivolts)
            if 0 < value < 65535:
                return value / 1000
        return None

    @staticmethod
    def _heading(value: Any) -> Optional[float]:
        if value is None:
            return None
        heading = float(value)
        if not math.isfinite(heading) or heading < 0:
            return None
        # MAVLink uses 36000 (centidegrees) and 65535 as unavailable heading
        # sentinels in different message dialects.
        if heading in {36000, 65535}:
            return None
        if heading > 360:
            heading /= 100
        if 0 <= heading < 360:
            return heading
        return None

    def _quality(self, now: datetime) -> TelemetryQuality:
        if self._last_position_at is None:
            return TelemetryQuality.UNKNOWN
        if self._last_heartbeat_at is None:
            return TelemetryQuality.DEGRADED
        heartbeat_age = max(0.0, (now - self._last_heartbeat_at).total_seconds())
        position_age = max(0.0, (now - self._last_position_at).total_seconds())
        if heartbeat_age >= self.lost_after_s or position_age >= self.lost_after_s:
            return TelemetryQuality.LOST
        if heartbeat_age >= self.stale_after_s or position_age >= self.stale_after_s:
            return TelemetryQuality.STALE
        if self._gps_fix_type is not None and self._gps_fix_type < 3:
            return TelemetryQuality.DEGRADED
        return TelemetryQuality.GOOD

    def _refresh_quality(self, now: datetime) -> None:
        if self._last_telemetry:
            self._last_telemetry = self._last_telemetry.model_copy(update={"quality": self._quality(now)})

    def _add_diagnostic(self, message: str) -> None:
        self._diagnostics.append(message)
        self._diagnostics = self._diagnostics[-20:]

    def snapshot(self, now: Optional[datetime] = None) -> VehicleStateSnapshot:
        now = now or self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("snapshot time must include a timezone")
        now = now.astimezone(timezone.utc)
        heartbeat_age = self._age(self._last_heartbeat_at, now)
        position_age = self._age(self._last_position_at, now)
        quality = self._quality(now)
        if heartbeat_age is None:
            connection = VehicleConnectionState.UNKNOWN
        elif heartbeat_age >= self.lost_after_s:
            connection = VehicleConnectionState.LOST
        elif heartbeat_age >= self.stale_after_s:
            connection = VehicleConnectionState.DEGRADED
        else:
            connection = VehicleConnectionState.CONNECTED
        if self._system_id is None:
            raise ValueError("cannot create a vehicle snapshot before receiving MAVLink data")
        if self._last_telemetry:
            telemetry = self._last_telemetry.model_copy(update={"quality": quality})
        else:
            telemetry = None
        return VehicleStateSnapshot(
            identity=VehicleIdentity(
                connector_vehicle_id=self.vehicle_id,
                mavlink_system_id=self._system_id,
                mavlink_component_ids=list(self._component_ids),
                autopilot_type=self._autopilot_type,
                vehicle_type=self._vehicle_type,
                firmware_version=self._firmware_version,
            ),
            connection_state=connection,
            telemetry=telemetry,
            quality=quality,
            health=VehicleHealth(
                heartbeat_age_s=heartbeat_age,
                position_age_s=position_age,
                gps_fix_type=self._gps_fix_type,
                satellites_visible=self._satellites_visible,
                battery_remaining_pct=self._battery_remaining_pct,
                battery_voltage_v=self._battery_voltage_v,
                armed=self._armed,
            ),
            mission_current=self._mission_current,
            mission_count=self._mission_count,
            diagnostics=list(self._diagnostics),
        )

    @staticmethod
    def _age(observed_at: Optional[datetime], now: datetime) -> Optional[float]:
        if observed_at is None:
            return None
        return max(0.0, (now - observed_at).total_seconds())


class MavlinkVehicleSession(MavlinkMessageNormalizer):
    """A non-commanding pymavlink session feeding the canonical normalizer.

    Telemetry is observed without vehicle-control commands. Mission drift
    checking may send MAVLink mission-protocol retrieval requests.
    """

    def __init__(
        self,
        vehicle_id: str,
        connection: Any,
        *,
        recorder: Optional[JsonlRecorder] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(vehicle_id, **kwargs)
        self.connection = connection
        self.recorder = recorder
        self._closed = False
        self._telemetry_stream_request_sent = False
        self.mission_reader = MavlinkMissionReader(vehicle_id, connection, clock=self.clock)

    @classmethod
    def connect(cls, vehicle_id: str, connection_uri: str, **kwargs: Any) -> "MavlinkVehicleSession":
        connection = mavutil.mavlink_connection(connection_uri)
        return cls(vehicle_id, connection, **kwargs)

    def poll(self, timeout: float = 0.0) -> Optional[Any]:
        message = self.connection.recv_match(blocking=timeout > 0, timeout=timeout or None)
        if message is not None:
            received_at = self.clock()
            self._record_raw_frame(message, received_at)
            self.ingest(message, received_at)
            if _message_type(message) == "HEARTBEAT":
                self._request_telemetry_streams()
            if self._system_id is not None and not self.mission_reader.requested:
                self.mission_reader.request_list(
                    system_id=self._system_id,
                    component_id=min(self._component_ids) if self._component_ids else 1,
                )
        return message

    def _request_telemetry_streams(self) -> None:
        """Ask an autopilot for the read-only streams needed by the connector.

        Some ArduPilot SITL and vehicle configurations emit heartbeats until a
        GCS requests stream rates. These are MAVLink telemetry-rate requests,
        not vehicle-control commands; they make the connector independent of
        whether QGroundControl or another GCS happened to request the streams
        first. A connection without this optional MAVLink helper remains a
        valid telemetry source and simply keeps its configured/default rates.
        """

        if self._telemetry_stream_request_sent:
            return
        self._telemetry_stream_request_sent = True
        sender = getattr(getattr(self.connection, "mav", None), "request_data_stream_send", None)
        if not callable(sender) or self._system_id is None:
            return

        target_component = min(self._component_ids) if self._component_ids else 1
        streams = (
            "MAV_DATA_STREAM_POSITION",
            "MAV_DATA_STREAM_EXTENDED_STATUS",
            "MAV_DATA_STREAM_EXTRA1",
            "MAV_DATA_STREAM_EXTRA2",
        )
        try:
            for stream_name in streams:
                stream_id = getattr(mavutil.mavlink, stream_name)
                sender(self._system_id, target_component, stream_id, 4, 1)
        except Exception as exc:
            self._add_diagnostic(f"MAVLink telemetry stream request unavailable: {exc}")

    def _record_raw_frame(self, message: Any, received_at: datetime) -> None:
        if self.recorder is None:
            return
        get_msgbuf = getattr(message, "get_msgbuf", None)
        if not callable(get_msgbuf):
            return
        try:
            frame = get_msgbuf()
            if frame is None:
                return
            self.recorder.record_mavlink_frame(
                self.vehicle_id,
                bytes(frame),
                received_at=received_at,
            )
        except Exception as exc:
            # Recording must never interrupt the independent telemetry path.
            self._add_diagnostic(f"MAVLink frame recording unavailable: {exc}")

    def ingest(self, message: Any, received_at: Optional[datetime] = None) -> None:
        super().ingest(message, received_at)
        try:
            self.mission_reader.ingest(message, received_at)
        except MissionParseError as exc:
            # A malformed or empty onboard mission must not interrupt the
            # independent telemetry stream. The diagnostic remains visible in
            # the canonical vehicle snapshot and an explicit refresh can retry.
            self._add_diagnostic(f"MAVLink mission unavailable: {exc}")

    @property
    def onboard_mission(self) -> Optional[MavlinkMissionRead]:
        return self.mission_reader.completed

    def request_mission(self) -> None:
        self.mission_reader.refresh()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()
