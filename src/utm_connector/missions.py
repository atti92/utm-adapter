"""Mission-source adapters that produce the canonical mission model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .domain import AltitudeDatum, Mission, Waypoint


class MissionParseError(ValueError):
    """Raised when a supported GCS mission cannot be normalized safely."""


def parse_qgroundcontrol_plan(
    payload: Mapping[str, Any],
    *,
    vehicle_id: str,
    valid_from: datetime,
    valid_until: datetime,
    corridor_radius_m: float = 30,
) -> Mission:
    """Parse basic QGroundControl SimpleItems into a canonical mission.

    QGC stores geographic coordinates in ``params[4:7]``.  The MAVLink frame
    is used to determine altitude semantics; the parser never guesses a datum.
    Complex items and unsupported command types are rejected for now so they
    cannot silently become a different operation.
    """

    if payload.get("fileType") != "Plan":
        raise MissionParseError("payload is not a QGroundControl Plan")
    mission_section = payload.get("mission")
    if not isinstance(mission_section, Mapping):
        raise MissionParseError("QGroundControl Plan is missing mission data")
    items = mission_section.get("items")
    if not isinstance(items, list):
        raise MissionParseError("QGroundControl Plan mission.items must be a list")

    waypoints = []
    for item in items:
        if not isinstance(item, Mapping) or item.get("type") != "SimpleItem":
            raise MissionParseError("only QGroundControl SimpleItem missions are supported")
        command = _integer(item.get("command"), "command")
        if command not in (16, 22):  # MAV_CMD_NAV_WAYPOINT / MAV_CMD_NAV_TAKEOFF
            raise MissionParseError(f"unsupported QGroundControl mission command: {command}")
        frame = _integer(item.get("frame"), "frame")
        datum = _altitude_datum(frame)
        params = item.get("params")
        if not isinstance(params, list) or len(params) < 7:
            raise MissionParseError("QGroundControl SimpleItem must contain seven params")
        try:
            latitude = float(params[4])
            longitude = float(params[5])
            altitude = float(params[6])
        except (TypeError, ValueError) as exc:
            raise MissionParseError("QGroundControl mission coordinates must be numeric") from exc
        waypoints.append(
            Waypoint(
                latitude=latitude,
                longitude=longitude,
                altitude={"meters": altitude, "datum": datum},
                sequence=len(waypoints),
            )
        )

    if len(waypoints) < 2:
        raise MissionParseError("QGroundControl mission must contain at least two navigable items")
    return Mission(
        vehicle_id=vehicle_id,
        waypoints=waypoints,
        corridor_radius_m=corridor_radius_m,
        valid_from=valid_from,
        valid_until=valid_until,
        source="qgroundcontrol",
    )


def parse_mission_planner_waypoints(
    payload: str,
    *,
    vehicle_id: str,
    valid_from: datetime,
    valid_until: datetime,
    corridor_radius_m: float = 30,
) -> Mission:
    """Parse Mission Planner's ``QGC WPL`` text export.

    Mission Planner uses the QGroundControl WPL 110 interchange format for
    waypoint files.  Only navigable commands are accepted because a UTM
    declaration must describe the actual route, not silently drop an action
    command from the GCS mission.
    """

    lines = [line.strip() for line in payload.lstrip("\ufeff").splitlines() if line.strip()]
    if not lines or not lines[0].startswith("QGC WPL "):
        raise MissionParseError("Mission Planner file must start with a QGC WPL header")

    waypoints = []
    expected_index = 0
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split()
        if len(fields) != 12:
            raise MissionParseError(
                f"Mission Planner waypoint line {line_number} must contain 12 fields"
            )
        try:
            index = int(fields[0])
            frame = int(fields[2])
            command = int(fields[3])
            latitude = float(fields[8])
            longitude = float(fields[9])
            altitude = float(fields[10])
        except (TypeError, ValueError) as exc:
            raise MissionParseError(
                f"Mission Planner waypoint line {line_number} contains invalid numeric data"
            ) from exc
        if index != expected_index:
            raise MissionParseError(
                f"Mission Planner waypoint indexes must be contiguous; expected {expected_index}"
            )
        if command not in (16, 22):  # MAV_CMD_NAV_WAYPOINT / MAV_CMD_NAV_TAKEOFF
            raise MissionParseError(
                f"unsupported Mission Planner mission command on line {line_number}: {command}"
            )
        datum = _altitude_datum(frame)
        waypoints.append(
            Waypoint(
                latitude=latitude,
                longitude=longitude,
                altitude={"meters": altitude, "datum": datum},
                sequence=len(waypoints),
            )
        )
        expected_index += 1

    if len(waypoints) < 2:
        raise MissionParseError("Mission Planner mission must contain at least two navigable items")
    return Mission(
        vehicle_id=vehicle_id,
        waypoints=waypoints,
        corridor_radius_m=corridor_radius_m,
        valid_from=valid_from,
        valid_until=valid_until,
        source="mission-planner",
    )


def _integer(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise MissionParseError(f"QGroundControl {field_name} must be an integer") from exc


def _altitude_datum(frame: int) -> AltitudeDatum:
    if frame in (0, 5):  # MAV_FRAME_GLOBAL / MAV_FRAME_GLOBAL_INT
        return AltitudeDatum.AMSL
    if frame in (3, 6):  # MAV_FRAME_GLOBAL_RELATIVE_ALT(_INT)
        return AltitudeDatum.AGL
    raise MissionParseError(f"unsupported QGroundControl altitude frame: {frame}")


def mavlink_altitude_datum(frame: int) -> AltitudeDatum:
    """Map a MAVLink global mission frame to an explicit altitude datum."""

    try:
        return _altitude_datum(frame)
    except MissionParseError as exc:
        raise MissionParseError(f"unsupported MAVLink mission altitude frame: {frame}") from exc
