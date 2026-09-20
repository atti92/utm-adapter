"""Generate a short WGS84 mission suitable for a local Flight Blender test."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


NAVIGABLE_COMMANDS = (22, 21)


def build_mission(
    *,
    vehicle_id: str,
    latitude: float,
    longitude: float,
    altitude_m: float,
    altitude_span_m: float,
    duration_minutes: int,
    start_offset_minutes: float,
) -> dict[str, object]:
    if altitude_span_m <= 0:
        raise ValueError("altitude_span_m must be greater than zero")
    start = datetime.now(timezone.utc) + timedelta(minutes=start_offset_minutes)
    end = start + timedelta(minutes=duration_minutes)
    half_span = altitude_span_m / 2
    return {
        "vehicle_id": vehicle_id,
        "valid_from": start.isoformat().replace("+00:00", "Z"),
        "valid_until": end.isoformat().replace("+00:00", "Z"),
        "source": "local-test",
        "corridor_radius_m": 30,
        "waypoints": [
            {
                "sequence": 0,
                "latitude": latitude,
                "longitude": longitude,
                "altitude": {"meters": altitude_m - half_span, "datum": "WGS84"},
            },
            {
                "sequence": 1,
                "latitude": latitude + 0.0005,
                "longitude": longitude + 0.0005,
                "altitude": {"meters": altitude_m + half_span, "datum": "WGS84"},
            },
        ],
    }


def _mission_points(payload: dict[str, object]) -> list[dict[str, float]]:
    waypoints = payload.get("waypoints")
    if not isinstance(waypoints, list) or len(waypoints) < 2:
        raise ValueError("mission must contain at least two waypoints")

    points: list[dict[str, float]] = []
    for waypoint in waypoints:
        if not isinstance(waypoint, dict):
            raise ValueError("mission waypoints must be objects")
        altitude = waypoint.get("altitude")
        if not isinstance(altitude, dict):
            raise ValueError("mission waypoint altitude must be an object")
        points.append(
            {
                "latitude": float(waypoint["latitude"]),
                "longitude": float(waypoint["longitude"]),
                "altitude": float(altitude["meters"]),
            }
        )
    return points


def build_qgroundcontrol_plan(payload: dict[str, object]) -> dict[str, object]:
    """Convert a canonical test mission to a simple QGroundControl Plan."""

    points = _mission_points(payload)
    items = []
    for sequence, (command, point) in enumerate(zip(NAVIGABLE_COMMANDS, points)):
        items.append(
            {
                "type": "SimpleItem",
                "command": command,
                "frame": 5,
                "autoContinue": True,
                "doJumpId": sequence + 1,
                "params": [
                    0,
                    0,
                    0,
                    0,
                    point["latitude"],
                    point["longitude"],
                    point["altitude"],
                ],
            }
        )
    return {
        "fileType": "Plan",
        "geoFence": {"circles": [], "polygons": [], "version": 2},
        "groundStation": "QGroundControl",
        "mission": {
            "cruiseSpeed": 15,
            "firmwareType": 3,
            "globalPlanAltitudeMode": 0,
            "hoverSpeed": 5,
            "items": items,
            "plannedHomePosition": [
                points[0]["latitude"],
                points[0]["longitude"],
                points[0]["altitude"],
            ],
            "vehicleType": 2,
            "version": 2,
        },
        "rallyPoints": {"points": [], "version": 2},
        "version": 1,
    }


def build_mission_planner_waypoints(payload: dict[str, object]) -> str:
    """Convert a canonical test mission to Mission Planner's QGC WPL text."""

    lines = ["QGC WPL 110"]
    for sequence, (command, point) in enumerate(zip(NAVIGABLE_COMMANDS, _mission_points(payload))):
        current = 1 if sequence == 0 else 0
        lines.append(
            "{sequence} {current} 5 {command} 0 0 0 0 {latitude} {longitude} {altitude} 1".format(
                sequence=sequence,
                current=current,
                command=command,
                latitude=point["latitude"],
                longitude=point["longitude"],
                altitude=point["altitude"],
            )
        )
    return "\n".join(lines) + "\n"


def write_demo_mission_files(output_dir: Path, *, vehicle_id: str = "sitl-1") -> dict[str, Path]:
    """Write canonical, QGroundControl, and Mission Planner demo artifacts."""

    payload = build_mission(
        vehicle_id=vehicle_id,
        latitude=47.4979,
        longitude=19.0402,
        altitude_m=120,
        altitude_span_m=4,
        duration_minutes=20,
        start_offset_minutes=1,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = output_dir / "mission.json"
    qgroundcontrol_path = output_dir / "mission-qgroundcontrol.plan"
    mission_planner_path = output_dir / "mission-planner.waypoints"
    canonical_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    qgroundcontrol_path.write_text(
        json.dumps(build_qgroundcontrol_plan(payload), indent=2) + "\n", encoding="utf-8"
    )
    mission_planner_path.write_text(build_mission_planner_waypoints(payload), encoding="utf-8")
    return {
        "canonical": canonical_path,
        "qgroundcontrol": qgroundcontrol_path,
        "mission-planner": mission_planner_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vehicle-id", default="sitl-1")
    parser.add_argument("--latitude", type=float, default=47.4979)
    parser.add_argument("--longitude", type=float, default=19.0402)
    parser.add_argument("--altitude-m", type=float, default=120)
    parser.add_argument(
        "--altitude-span-m",
        type=float,
        default=4,
        help="vertical WGS84 band centered on --altitude-m (default: 4 m)",
    )
    parser.add_argument("--duration-minutes", type=int, default=20)
    parser.add_argument(
        "--start-offset-minutes",
        type=float,
        default=1.0,
        help="Minutes from now when the mission starts; default 1.0 leaves room for provider clock skew",
    )
    args = parser.parse_args()

    payload = build_mission(
        vehicle_id=args.vehicle_id,
        latitude=args.latitude,
        longitude=args.longitude,
        altitude_m=args.altitude_m,
        altitude_span_m=args.altitude_span_m,
        duration_minutes=args.duration_minutes,
        start_offset_minutes=args.start_offset_minutes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
