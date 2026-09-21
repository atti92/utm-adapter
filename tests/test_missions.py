from datetime import datetime, timezone

import pytest

from utm_connector.domain import AltitudeDatum
from utm_connector.missions import (
    MissionParseError,
    parse_mission_planner_waypoints,
    parse_qgroundcontrol_plan,
)


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


def test_qgroundcontrol_plan_accepts_standard_coordinate_items() -> None:
    plan = {
        "fileType": "Plan",
        "geoFence": {"polygon": [], "version": 1},
        "groundStation": "QGroundControl",
        "mission": {
            "items": [
                {
                    "autoContinue": True,
                    "command": 22,
                    "coordinate": [47.5, 19.05, 100],
                    "doJumpId": 1,
                    "frame": 3,
                    "params": [0, 0, 0, None],
                    "type": "SimpleItem",
                },
                {
                    "autoContinue": True,
                    "command": 16,
                    "coordinate": [47.501, 19.052, 120],
                    "doJumpId": 2,
                    "frame": 3,
                    "params": [0, 0, 0, None],
                    "type": "SimpleItem",
                },
            ]
        },
    }

    mission = parse_qgroundcontrol_plan(
        plan,
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert mission.waypoints[0].latitude == 47.5
    assert mission.waypoints[1].longitude == 19.052
    assert mission.waypoints[0].altitude.datum == AltitudeDatum.AGL


def test_qgroundcontrol_plan_accepts_a_geographic_landing_endpoint() -> None:
    plan = _plan()
    plan["mission"]["items"].append(
        {
            "type": "SimpleItem",
            "command": 21,
            "frame": 6,
            "params": [0, 0, 0, 0, 47.502, 19.053, 0],
        }
    )

    mission = parse_qgroundcontrol_plan(
        plan,
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert len(mission.waypoints) == 3
    assert mission.waypoints[-1].latitude == 47.502
    assert mission.waypoints[-1].altitude.meters == 0


def test_qgroundcontrol_plan_ignores_a_final_return_to_launch_item() -> None:
    plan = _plan()
    plan["mission"]["items"].append(
        {
            "type": "SimpleItem",
            "command": 20,
            "frame": 2,
            "params": [0, 0, 0, 0, 0, 0, 0],
        }
    )

    mission = parse_qgroundcontrol_plan(
        plan,
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert len(mission.waypoints) == 2
    assert [waypoint.sequence for waypoint in mission.waypoints] == [0, 1]


def test_qgroundcontrol_plan_rejects_return_to_launch_before_the_final_item() -> None:
    plan = _plan()
    plan["mission"]["items"].insert(
        1,
        {
            "type": "SimpleItem",
            "command": 20,
            "frame": 2,
            "params": [0, 0, 0, 0, 0, 0, 0],
        },
    )

    with pytest.raises(MissionParseError, match="must be the final mission item"):
        parse_qgroundcontrol_plan(
            plan,
            vehicle_id="sitl-1",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )


def test_qgroundcontrol_plan_rejects_unsupported_altitude_frame() -> None:
    with pytest.raises(MissionParseError, match="altitude frame"):
        parse_qgroundcontrol_plan(
            _plan(frame=10),
            vehicle_id="sitl-1",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )


def _mission_planner_file(frame: int = 3) -> str:
    return "\n".join(
        [
            "QGC WPL 110",
            f"0\t1\t{frame}\t22\t0\t0\t0\t0\t47.5\t19.05\t100\t1",
            f"1\t0\t{frame}\t16\t0\t0\t0\t0\t47.501\t19.052\t120\t1",
        ]
    )


def test_mission_planner_wpl_maps_coordinates_and_altitude_frame() -> None:
    mission = parse_mission_planner_waypoints(
        _mission_planner_file(),
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert mission.source == "mission-planner"
    assert mission.waypoints[0].latitude == 47.5
    assert mission.waypoints[1].longitude == 19.052
    assert mission.waypoints[0].altitude.datum == AltitudeDatum.AGL


def test_mission_planner_wpl_accepts_a_geographic_landing_endpoint() -> None:
    payload = _mission_planner_file() + (
        "\n2\t0\t3\t21\t0\t0\t0\t0\t47.502\t19.053\t0\t1"
    )

    mission = parse_mission_planner_waypoints(
        payload,
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert len(mission.waypoints) == 3
    assert mission.waypoints[-1].longitude == 19.053


def test_mission_planner_wpl_ignores_a_final_return_to_launch_item() -> None:
    payload = _mission_planner_file() + (
        "\n2\t0\t2\t20\t0\t0\t0\t0\t0\t0\t0\t1"
    )

    mission = parse_mission_planner_waypoints(
        payload,
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert len(mission.waypoints) == 2
    assert [waypoint.sequence for waypoint in mission.waypoints] == [0, 1]


def test_mission_planner_wpl_rejects_non_route_commands() -> None:
    payload = _mission_planner_file().replace("\t16\t", "\t178\t")
    with pytest.raises(MissionParseError, match="unsupported Mission Planner mission command"):
        parse_mission_planner_waypoints(
            payload,
            vehicle_id="sitl-1",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )


def test_mission_planner_wpl_rejects_malformed_header() -> None:
    with pytest.raises(MissionParseError, match="QGC WPL header"):
        parse_mission_planner_waypoints(
            "0 1 3 16 0 0 0 0 47.5 19.0 100 1",
            vehicle_id="sitl-1",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )
