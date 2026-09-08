"""Generate a short WGS84 mission suitable for a local Flight Blender test."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vehicle-id", default="sitl-1")
    parser.add_argument("--latitude", type=float, default=47.4979)
    parser.add_argument("--longitude", type=float, default=19.0402)
    parser.add_argument("--altitude-m", type=float, default=120)
    parser.add_argument("--duration-minutes", type=int, default=20)
    args = parser.parse_args()

    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    end = start + timedelta(minutes=args.duration_minutes)
    payload = {
        "vehicle_id": args.vehicle_id,
        "valid_from": start.isoformat().replace("+00:00", "Z"),
        "valid_until": end.isoformat().replace("+00:00", "Z"),
        "source": "local-test",
        "corridor_radius_m": 30,
        "waypoints": [
            {
                "sequence": 0,
                "latitude": args.latitude,
                "longitude": args.longitude,
                "altitude": {"meters": args.altitude_m, "datum": "WGS84"},
            },
            {
                "sequence": 1,
                "latitude": args.latitude + 0.0005,
                "longitude": args.longitude + 0.0005,
                "altitude": {"meters": args.altitude_m, "datum": "WGS84"},
            },
        ],
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
