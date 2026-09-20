import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.verify_running_demo import _mission_upload, verify_running_demo
from utm_connector.missions import parse_mission_planner_waypoints, parse_qgroundcontrol_plan


def test_running_demo_verifier_exercises_operator_console_lifecycle() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path))
        if path == "/v1/health":
            return httpx.Response(200, json={"status": "ok", "backend_error": None})
        if path == "/v1/metrics":
            return httpx.Response(
                200,
                json={
                    "telemetry": {"received_total": 1},
                    "vehicles": {"active": 1},
                },
            )
        if path == "/v1/vehicles/sitl-1/status":
            return httpx.Response(
                200,
                json={
                    "latest_telemetry": {
                        "latitude": 47.4979,
                        "longitude": 19.0402,
                        "altitude": {"meters": 137.0, "datum": "AMSL"},
                    }
                },
            )
        if path == "/v1/missions/sitl-1":
            assert request.method == "PUT"
            mission = json.loads(request.content)
            assert mission["source"] == "operator-console-full-stack-verification"
            assert len(mission["waypoints"]) == 3
            return httpx.Response(200, json={"mission_hash": "test"})
        if path == "/v1/operator-intents":
            intent = json.loads(request.content)
            command = intent["command"]
            states = {
                "SUBMIT_OPERATION": {
                    "declaration": "ACCEPTED",
                    "authorization": "AUTHORIZED",
                    "conformance": "UNKNOWN",
                    "telemetry_publication": "INACTIVE",
                },
                "START_OPERATION": {
                    "declaration": "ACCEPTED",
                    "authorization": "AUTHORIZED",
                    "conformance": "UNKNOWN",
                    "telemetry_publication": "ACTIVE",
                },
                "COMPLETE_OPERATION": {
                    "declaration": "COMPLETED",
                    "authorization": "AUTHORIZED",
                    "conformance": "CONFORMING",
                    "telemetry_publication": "STOPPED",
                },
            }
            return httpx.Response(201, json={"state": states[command]})
        if path.startswith("/v1/operations/"):
            return httpx.Response(
                200,
                json={
                    "state": {
                        "declaration": "ACCEPTED",
                        "authorization": "AUTHORIZED",
                        "conformance": "CONFORMING",
                        "telemetry_publication": "ACTIVE",
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = verify_running_demo(
            "http://demo",
            "sitl-1",
            poll_interval_s=0,
            client=client,
        )

    assert result.vehicle_id == "sitl-1"
    assert result.operation_id
    assert calls == [
        ("GET", "/v1/health"),
        ("GET", "/v1/vehicles/sitl-1/status"),
        ("PUT", "/v1/missions/sitl-1"),
        ("POST", "/v1/operator-intents"),
        ("POST", "/v1/operator-intents"),
        ("GET", f"/v1/operations/{result.operation_id}"),
        ("POST", "/v1/operator-intents"),
        ("GET", "/v1/health"),
        ("GET", "/v1/metrics"),
    ]


def test_running_demo_verifier_builds_a_real_qgroundcontrol_plan_upload() -> None:
    path, payload = _mission_upload(
        vehicle_id="sitl-1",
        latitude=47.4979,
        longitude=19.0402,
        altitude_m=137,
        altitude_datum="AMSL",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        mission_format="qgroundcontrol",
    )

    assert path == "/v1/missions/sitl-1/qgroundcontrol"
    mission = parse_qgroundcontrol_plan(
        payload["plan"],
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        corridor_radius_m=payload["corridor_radius_m"],
    )
    assert mission.source == "qgroundcontrol"
    assert len(mission.waypoints) == 3
    assert mission.waypoints[1].longitude == pytest.approx(19.0404)


def test_running_demo_verifier_builds_a_real_mission_planner_wpl_upload() -> None:
    path, payload = _mission_upload(
        vehicle_id="sitl-1",
        latitude=47.4979,
        longitude=19.0402,
        altitude_m=137,
        altitude_datum="AMSL",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        mission_format="mission-planner",
    )

    assert path == "/v1/missions/sitl-1/mission-planner"
    mission = parse_mission_planner_waypoints(
        payload["text"],
        vehicle_id="sitl-1",
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        corridor_radius_m=payload["corridor_radius_m"],
    )
    assert mission.source == "mission-planner"
    assert len(mission.waypoints) == 3
    assert mission.waypoints[2].latitude == 47.4979
