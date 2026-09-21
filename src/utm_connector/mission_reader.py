"""Read-only MAVLink mission protocol support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from pymavlink import mavutil

from .domain import Altitude, Mission, Waypoint
from .missions import (
    IGNORED_TERMINAL_MISSION_COMMANDS,
    NAVIGABLE_MISSION_COMMANDS,
    MissionParseError,
    mavlink_altitude_datum,
    validate_terminal_mission_command_position,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class MavlinkMissionRead:
    """A complete onboard mission before UTM-only metadata is applied."""

    vehicle_id: str
    waypoints: tuple[Waypoint, ...]
    mission_count: int
    received_at: datetime

    def to_mission(self, template: Mission) -> Mission:
        """Apply submitted-operation metadata to the onboard route.

        MAVLink mission items do not carry UTM validity windows or corridor
        radius. Those fields must come from an explicit submitted mission;
        this method never invents them.
        """

        if template.vehicle_id != self.vehicle_id:
            raise MissionParseError("mission template vehicle_id does not match onboard mission")
        return template.model_copy(
            update={
                "waypoints": list(self.waypoints),
                "source": "mavlink",
            }
        )


class MavlinkMissionReader:
    """Request and reconstruct a vehicle mission using MAVLink mission items."""

    def __init__(
        self,
        vehicle_id: str,
        connection: Any,
        *,
        max_items: int = 1000,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_items < 2:
            raise ValueError("max_items must be at least two")
        self.vehicle_id = vehicle_id
        self.connection = connection
        self.max_items = max_items
        self.clock = clock
        self._target_system: Optional[int] = None
        self._target_component: Optional[int] = None
        self._expected_count: Optional[int] = None
        self._items: Dict[int, Waypoint] = {}
        self._received_sequences: set[int] = set()
        self._requested = False
        self._completed: Optional[MavlinkMissionRead] = None
        self._last_ack: Optional[int] = None

    @property
    def requested(self) -> bool:
        return self._requested

    @property
    def completed(self) -> Optional[MavlinkMissionRead]:
        return self._completed

    @property
    def last_ack(self) -> Optional[int]:
        return self._last_ack

    def set_target(self, system_id: int, component_id: int = 1) -> None:
        if not 1 <= system_id <= 255 or not 1 <= component_id <= 255:
            raise ValueError("MAVLink target IDs must be between 1 and 255")
        self._target_system = system_id
        self._target_component = component_id

    def request_list(self, *, system_id: Optional[int] = None, component_id: Optional[int] = None) -> None:
        if system_id is not None:
            self.set_target(system_id, component_id or 1)
        if self._target_system is None or self._target_component is None:
            raise MissionParseError("cannot request mission before discovering a MAVLink target")
        sender = getattr(getattr(self.connection, "mav", None), "mission_request_list_send", None)
        if not callable(sender):
            raise MissionParseError("MAVLink connection cannot request a mission list")
        self._expected_count = None
        self._items = {}
        self._received_sequences = set()
        self._completed = None
        self._last_ack = None
        sender(self._target_system, self._target_component)
        self._requested = True

    def refresh(self) -> None:
        """Request a fresh onboard mission after a previous read completed."""

        self.request_list()

    def ingest(self, message: Any, received_at: Optional[datetime] = None) -> Optional[MavlinkMissionRead]:
        received_at = received_at or self.clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        received_at = received_at.astimezone(timezone.utc)
        message_type = _message_type(message)
        if message_type == "HEARTBEAT":
            autopilot = getattr(message, "autopilot", None)
            if autopilot is not None and int(autopilot) == int(mavutil.mavlink.MAV_AUTOPILOT_INVALID):
                return None
            system_id = _source_id(message, "get_srcSystem")
            if self._target_system is not None and system_id != self._target_system:
                return None
            self.set_target(system_id, _source_id(message, "get_srcComponent", 1))
            return None
        source_system = _source_id(message, "get_srcSystem")
        if self._target_system is not None and source_system and source_system != self._target_system:
            return None
        if message_type == "MISSION_COUNT":
            if not self._requested:
                return None
            return self._ingest_count(message)
        if message_type in {"MISSION_ITEM", "MISSION_ITEM_INT"}:
            if not self._requested:
                return None
            return self._ingest_item(message, received_at, message_type)
        if message_type == "MISSION_ACK":
            self._last_ack = int(getattr(message, "type", -1))
        return None

    def _ingest_count(self, message: Any) -> Optional[MavlinkMissionRead]:
        count = int(getattr(message, "count", -1))
        if count < 0 or count > self.max_items:
            raise MissionParseError(f"MAVLink mission count is outside the supported range: {count}")
        self.set_target(_source_id(message, "get_srcSystem"), _source_id(message, "get_srcComponent", 1))
        self._expected_count = count
        self._items = {}
        self._received_sequences = set()
        self._completed = None
        if count == 0:
            raise MissionParseError("MAVLink vehicle reported an empty mission")
        self._request_item(0)
        return None

    def _ingest_item(
        self, message: Any, received_at: datetime, message_type: str
    ) -> Optional[MavlinkMissionRead]:
        if self._expected_count is None:
            return None
        sequence = int(getattr(message, "seq", -1))
        if sequence < 0 or sequence >= self._expected_count:
            raise MissionParseError(f"MAVLink mission item sequence is invalid: {sequence}")
        if sequence in self._received_sequences:
            return self._completed
        self._received_sequences.add(sequence)
        command = int(getattr(message, "command", -1))
        if command in IGNORED_TERMINAL_MISSION_COMMANDS:
            validate_terminal_mission_command_position(
                command,
                sequence,
                self._expected_count,
                source="MAVLink",
            )
        else:
            waypoint = _waypoint_from_item(message, message_type)
            self._items[len(self._items)] = waypoint.model_copy(
                update={"sequence": len(self._items)}
            )
        if len(self._received_sequences) < self._expected_count:
            self._request_item(
                _next_missing_sequence(self._received_sequences, self._expected_count)
            )
            return None

        if self._received_sequences != set(range(self._expected_count)):
            raise MissionParseError("MAVLink mission items are incomplete")
        if len(self._items) < 2:
            raise MissionParseError("MAVLink mission must contain at least two navigable items")
        self._completed = MavlinkMissionRead(
            vehicle_id=self.vehicle_id,
            waypoints=tuple(self._items[index] for index in range(len(self._items))),
            mission_count=self._expected_count,
            received_at=received_at,
        )
        self._requested = False
        self._ack()
        return self._completed

    def _request_item(self, sequence: int) -> None:
        if self._target_system is None or self._target_component is None:
            raise MissionParseError("cannot request mission item before discovering a MAVLink target")
        mav = getattr(self.connection, "mav", None)
        sender = getattr(mav, "mission_request_int_send", None)
        if callable(sender):
            sender(self._target_system, self._target_component, sequence)
            return
        sender = getattr(mav, "mission_request_send", None)
        if not callable(sender):
            raise MissionParseError("MAVLink connection cannot request mission items")
        sender(self._target_system, self._target_component, sequence)

    def _ack(self) -> None:
        if self._target_system is None or self._target_component is None:
            return
        sender = getattr(getattr(self.connection, "mav", None), "mission_ack_send", None)
        if callable(sender):
            sender(self._target_system, self._target_component, mavutil.mavlink.MAV_MISSION_ACCEPTED)


def _message_type(message: Any) -> str:
    getter = getattr(message, "get_type", None)
    return getter() if callable(getter) else str(getattr(message, "_type", "UNKNOWN"))


def _source_id(message: Any, name: str, default: int = 0) -> int:
    getter = getattr(message, name, None)
    if callable(getter):
        return int(getter())
    return int(getattr(message, name.replace("get_", ""), default))


def _waypoint_from_item(message: Any, message_type: str = "MISSION_ITEM_INT") -> Waypoint:
    command = int(getattr(message, "command", -1))
    if command not in NAVIGABLE_MISSION_COMMANDS:
        raise MissionParseError(f"unsupported MAVLink mission command: {command}")
    frame = int(getattr(message, "frame", -1))
    datum = mavlink_altitude_datum(frame)
    try:
        latitude = float(getattr(message, "x"))
        longitude = float(getattr(message, "y"))
        if message_type == "MISSION_ITEM_INT":
            latitude /= 10_000_000
            longitude /= 10_000_000
        altitude = float(getattr(message, "z"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise MissionParseError("MAVLink mission coordinates must be numeric") from exc
    return Waypoint(
        latitude=latitude,
        longitude=longitude,
        altitude=Altitude(meters=altitude, datum=datum),
        sequence=int(getattr(message, "seq")),
    )


def _next_missing_sequence(items: set[int], count: int) -> int:
    for sequence in range(count):
        if sequence not in items:
            return sequence
    raise MissionParseError("no missing MAVLink mission item remains")
