from datetime import datetime, timezone

import pytest

from utm_connector.domain import AltitudeDatum
from utm_connector.missions import MissionParseError, parse_qgroundcontrol_plan


def _plan(frame: int = 6) -> dict:
    def item(command: int, latitude: float, longitude: float, altitude: float) -> dict:
        return {
            "type": "SimpleItem",
            "command": command,
            "frame": frame,
            "params": [0, 0, 0, 0, latitude, longitude, altitude],
        }

    return {
        "fileType": "Plan",
        "mission": {"items": [item(22, 47.5, 19.05, 100), item(16, 47.501, 19.052, 120)]},
    }


def test_qgroundcontrol_plan_maps_frames_and_coordinates() -> None:
    mission = parse_qgroundcontrol_plan(
        _plan(),
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert mission.source == "qgroundcontrol"
    assert mission.waypoints[0].latitude == 47.5
    assert mission.waypoints[1].longitude == 19.052
    assert mission.waypoints[0].altitude.datum == AltitudeDatum.AGL


def test_qgroundcontrol_plan_rejects_unsupported_altitude_frame() -> None:
    with pytest.raises(MissionParseError, match="altitude frame"):
        parse_qgroundcontrol_plan(
            _plan(frame=10),
            vehicle_id="sitl-1",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )
