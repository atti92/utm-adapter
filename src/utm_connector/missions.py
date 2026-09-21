"""Mission-source adapters that produce the canonical mission model."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from .domain import Altitude, AltitudeDatum, AltitudeReference, Mission, Waypoint


class MissionParseError(ValueError):
    """Raised when a supported GCS mission cannot be normalized safely."""


# These commands each describe a geographic route point. Other MAVLink
# mission commands may change vehicle behavior without describing a point that
# can be represented by the connector's corridor-only Mission model, so they
# remain rejected instead of being silently discarded.
NAVIGABLE_MISSION_COMMANDS = frozenset({16, 21, 22})
NAVIGABLE_MISSION_COMMANDS_INFO = (
    {"command": 16, "name": "WAYPOINT", "role": "route_point"},
    {"command": 21, "name": "LAND", "role": "route_endpoint"},
    {"command": 22, "name": "TAKEOFF", "role": "route_point"},
)

# QGroundControl and Mission Planner commonly append RTL to an otherwise
# geographic mission. RTL has no route coordinate: it is an autopilot action
# that must remain with the GCS/autopilot, not become a fake (0, 0) waypoint.
# It is therefore accepted only as the final item and intentionally omitted
# from the canonical UTM route.
IGNORED_TERMINAL_MISSION_COMMANDS = frozenset({20})
IGNORED_TERMINAL_MISSION_COMMANDS_INFO = (
    {"command": 20, "name": "RETURN_TO_LAUNCH", "role": "terminal_behavior_ignored"},
)


def parse_qgroundcontrol_plan(
    payload: Mapping[str, Any],
    *,
    vehicle_id: str,
    valid_from: datetime,
    valid_until: datetime,
    corridor_radius_m: float = 30,
) -> Mission:
    """Parse basic QGroundControl SimpleItems into a canonical mission.

    QGC Plans encode MAVLink geographic coordinates in ``params[4:7]``. Some
    exports also include a convenience ``coordinate`` field; both
    representations are accepted for compatibility. When both are present,
    non-placeholder MAVLink coordinates take precedence so a stale repeated
    convenience value cannot collapse the route geometry. The MAVLink frame
    is used to determine altitude semantics; the parser never guesses a datum.
    Complex items and unsupported command types are rejected so they cannot
    silently become a different operation. Waypoint, takeoff, and landing
    items are represented by their geographic route point; vehicle-control
    behavior remains with the GCS/autopilot.
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
    uses_relative_altitude = False
    for item_index, item in enumerate(items):
        if not isinstance(item, Mapping) or item.get("type") != "SimpleItem":
            raise MissionParseError("only QGroundControl SimpleItem missions are supported")
        command = _integer(item.get("command"), "command")
        if command in IGNORED_TERMINAL_MISSION_COMMANDS:
            validate_terminal_mission_command_position(
                command,
                item_index,
                len(items),
                source="QGroundControl",
            )
            continue
        if command not in NAVIGABLE_MISSION_COMMANDS:
            raise MissionParseError(f"unsupported QGroundControl mission command: {command}")
        frame = _integer(item.get("frame"), "frame")
        datum = _altitude_datum(frame)
        uses_relative_altitude = uses_relative_altitude or datum == AltitudeDatum.AGL
        coordinate_values = _qgroundcontrol_item_coordinates(item)
        try:
            latitude = float(coordinate_values[0])
            longitude = float(coordinate_values[1])
            altitude = float(coordinate_values[2])
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
        altitude_reference=(
            _qgroundcontrol_altitude_reference(mission_section)
            if uses_relative_altitude
            else None
        ),
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
    mission_item_count = len(lines) - 1
    for item_index, (line_number, line) in enumerate(zip(range(2, len(lines) + 1), lines[1:])):
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
        if command in IGNORED_TERMINAL_MISSION_COMMANDS:
            validate_terminal_mission_command_position(
                command,
                item_index,
                mission_item_count,
                source="Mission Planner",
            )
            expected_index += 1
            continue
        if command not in NAVIGABLE_MISSION_COMMANDS:
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


def _qgroundcontrol_item_coordinates(item: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    """Return the most reliable geographic coordinates from a QGC item.

    QGroundControl exports have used both a convenience ``coordinate`` field
    and the MAVLink ``params[4:7]`` fields.  Some generated plans retain a
    stale home coordinate in the former while carrying the actual route point
    in the latter.  Prefer non-placeholder MAVLink coordinates when both are
    available, while still accepting older coordinate-only exports.
    """

    coordinate_values = _numeric_coordinate_candidate(item.get("coordinate"))
    params = item.get("params")
    params_values = (
        _numeric_coordinate_candidate(params[4:7])
        if isinstance(params, list) and len(params) >= 7
        else None
    )

    if params_values is not None and _has_geographic_position(params_values):
        return params_values
    if coordinate_values is not None:
        return coordinate_values
    if params_values is not None:
        return params_values
    if item.get("coordinate") is not None:
        raise MissionParseError(
            "QGroundControl SimpleItem coordinate must contain latitude, longitude, and altitude"
        )
    raise MissionParseError("QGroundControl SimpleItem must contain coordinate or seven params")


def _numeric_coordinate_candidate(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        latitude = float(value[0])
        longitude = float(value[1])
        altitude = float(value[2])
    except (TypeError, ValueError):
        return None
    if not all(isfinite(number) for number in (latitude, longitude, altitude)):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude, altitude


def _has_geographic_position(value: tuple[float, float, float]) -> bool:
    """Identify the all-zero coordinate often used as a QGC placeholder."""

    return abs(value[0]) > 1e-12 or abs(value[1]) > 1e-12


def validate_terminal_mission_command_position(
    command: int,
    item_index: int,
    item_count: int,
    *,
    source: str,
) -> None:
    """Ensure an ignored terminal behavior cannot interrupt the route."""

    if command not in IGNORED_TERMINAL_MISSION_COMMANDS:
        return
    if item_index != item_count - 1:
        name = next(
            item["name"]
            for item in IGNORED_TERMINAL_MISSION_COMMANDS_INFO
            if item["command"] == command
        )
        raise MissionParseError(
            f"{source} {name} must be the final mission item; "
            "terminal behavior is not part of the UTM route"
        )


def _altitude_datum(frame: int) -> AltitudeDatum:
    if frame in (0, 5):  # MAV_FRAME_GLOBAL / MAV_FRAME_GLOBAL_INT
        return AltitudeDatum.AMSL
    if frame in (3, 6):  # MAV_FRAME_GLOBAL_RELATIVE_ALT(_INT)
        return AltitudeDatum.AGL
    raise MissionParseError(f"unsupported QGroundControl altitude frame: {frame}")


def _qgroundcontrol_altitude_reference(
    mission_section: Mapping[str, Any],
) -> AltitudeReference | None:
    """Read QGC's planned home, which is the reference for relative altitudes.

    QGroundControl stores the planned home altitude as AMSL. Keeping that
    datum explicit lets the provider boundary convert AGL -> AMSL -> WGS84
    without treating a relative altitude as an absolute height.
    """

    planned_home = mission_section.get("plannedHomePosition")
    if planned_home is None:
        return None
    if not isinstance(planned_home, (list, tuple)) or len(planned_home) < 3:
        raise MissionParseError(
            "QGroundControl relative-altitude mission plannedHomePosition "
            "must contain latitude, longitude, and AMSL altitude"
        )
    try:
        latitude = float(planned_home[0])
        longitude = float(planned_home[1])
        altitude = float(planned_home[2])
        return AltitudeReference(
            latitude=latitude,
            longitude=longitude,
            altitude=Altitude(meters=altitude, datum=AltitudeDatum.AMSL),
        )
    except (TypeError, ValueError) as exc:
        raise MissionParseError(
            "QGroundControl relative-altitude mission plannedHomePosition "
            "must contain numeric latitude, longitude, and AMSL altitude"
        ) from exc


def mavlink_altitude_datum(frame: int) -> AltitudeDatum:
    """Map a MAVLink global mission frame to an explicit altitude datum."""

    try:
        return _altitude_datum(frame)
    except MissionParseError as exc:
        raise MissionParseError(f"unsupported MAVLink mission altitude frame: {frame}") from exc
