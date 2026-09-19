"""Generate a short WGS84 mission suitable for a local Flight Blender test."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
