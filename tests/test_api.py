from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from utm_connector.api import create_app
from utm_connector.backends import InMemoryBackend
from utm_connector.config import ConnectorSettings, MavlinkConnectionConfig
from utm_connector.runtime import MavlinkSessionManager
from utm_connector.service import ConnectorService


def _mission() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "vehicle_id": "sitl-1",
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(minutes=30)).isoformat(),
        "source": "qgc.plan",
        "waypoints": [
            {"sequence": 0, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 20, "datum": "AGL"}},
            {"sequence": 1, "latitude": 47.501, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
        ],
    }


def test_local_operation_lifecycle() -> None:
    app = create_app(ConnectorService(InMemoryBackend()))
    client = TestClient(app)
    mission_response = client.put("/v1/missions/sitl-1", json=_mission())
    assert mission_response.status_code == 200
    assert len(mission_response.json()["mission_hash"]) == 64

    submission_id = uuid4()
    operation_response = client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"schema_version": "1.0", "command": "SUBMIT_OPERATION", "operation_id": str(submission_id)},
    )
    assert operation_response.status_code == 201
    operation = operation_response.json()
    operation_id = operation["operation_id"]
    assert operation_id == str(submission_id)
    assert operation["state"]["declaration"] == "ACCEPTED"
    assert operation["state"]["authorization"] == "AUTHORIZED"

    start_response = client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"schema_version": "1.0", "command": "START_OPERATION", "operation_id": operation_id},
    )
    assert start_response.status_code == 201
    assert start_response.json()["state"]["telemetry_publication"] == "ACTIVE"

    telemetry_response = client.put(
        "/v1/vehicles/sitl-1",
        json={
            "vehicle_id": "sitl-1",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "latitude": 47.5,
            "longitude": 19.0,
            "altitude": {"meters": 20, "datum": "AGL"},
            "quality": "GOOD",
        },
    )
    assert telemetry_response.status_code == 200
    status = client.get("/v1/vehicles/sitl-1/status").json()
    assert status["operations"][0]["state"]["conformance"] == "CONFORMING"
    assert client.get("/v1/health").json()["active_vehicles"] == 1
    assert len(client.get("/v1/events").json()) >= 5


def test_capabilities_and_vehicle_directory_are_gcs_friendly() -> None:
    client = TestClient(
        create_app(
            ConnectorService(InMemoryBackend()),
            ConnectorSettings(mavlink_connections=[]),
        )
    )
    capabilities = client.get("/v1/capabilities")

    assert capabilities.status_code == 200
    assert capabilities.json()["mavlink"] == {
        "configured": False,
        "read_only": True,
        "mission_download": True,
    }
    assert "qgroundcontrol" in capabilities.json()["mission_formats"]

    telemetry = {
        "vehicle_id": "sitl-1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "latitude": 47.5,
        "longitude": 19.0,
        "altitude": {"meters": 20, "datum": "AGL"},
        "quality": "GOOD",
    }
    assert client.put("/v1/vehicles/sitl-1", json=telemetry).status_code == 200

    vehicles = client.get("/v1/vehicles")
    assert vehicles.status_code == 200
    assert vehicles.json() == [
        {
            "vehicle_id": "sitl-1",
            "connection_state": "UNKNOWN",
            "quality": "GOOD",
            "mavlink_system_id": None,
            "latest_telemetry_at": telemetry["observed_at"],
            "active_operation_count": 0,
            "last_error": None,
        }
    ]


def test_vehicle_directory_reports_configured_session_before_first_heartbeat() -> None:
    service = ConnectorService(InMemoryBackend())

    def offline_factory(_vehicle_id: str, _uri: str) -> object:
        raise RuntimeError("simulator is offline")

    manager = MavlinkSessionManager(
        [
            MavlinkConnectionConfig(
                vehicle_id="sitl-1",
                connection_uri="udpin:127.0.0.1:14551",
            )
        ],
        lambda _snapshot: None,
        session_factory=offline_factory,
    )

    with TestClient(create_app(service, ConnectorSettings(mavlink_connections=[]), manager)) as client:
        assert client.get("/v1/health").json()["status"] == "degraded"
        assert client.get("/v1/vehicles").json() == [
            {
                "vehicle_id": "sitl-1",
                "connection_state": "UNKNOWN",
                "quality": "UNKNOWN",
                "mavlink_system_id": None,
                "latest_telemetry_at": None,
                "active_operation_count": 0,
                "last_error": "simulator is offline",
            }
        ]
        status = client.get("/v1/vehicles/sitl-1/status")
        assert status.status_code == 200
        assert status.json() == {
            "vehicle_id": "sitl-1",
            "vehicle_state": None,
            "latest_telemetry": None,
            "mission_drift": None,
            "operations": [],
            "last_error": "simulator is offline",
        }


def test_mission_and_telemetry_path_ids_are_checked() -> None:
    app = create_app(ConnectorService(InMemoryBackend()))
    client = TestClient(app)
    payload = _mission()
    payload["vehicle_id"] = "other"
    assert client.put("/v1/missions/sitl-1", json=payload).status_code == 422


def test_qgroundcontrol_plan_endpoint_normalizes_explicit_metadata() -> None:
    app = create_app(ConnectorService(InMemoryBackend()))
    client = TestClient(app)
    now = datetime.now(timezone.utc)
    response = client.put(
        "/v1/missions/sitl-1/qgroundcontrol",
        json={
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(minutes=30)).isoformat(),
            "corridor_radius_m": 40,
            "plan": {
                "fileType": "Plan",
                "mission": {
                    "items": [
                        {"type": "SimpleItem", "command": 22, "frame": 3, "params": [0, 0, 0, 0, 47.5, 19.0, 20]},
                        {"type": "SimpleItem", "command": 16, "frame": 3, "params": [0, 0, 0, 0, 47.501, 19.001, 25]},
                    ]
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["mission"]["source"] == "qgroundcontrol"
    assert response.json()["mission"]["corridor_radius_m"] == 40


def test_qgroundcontrol_plan_endpoint_rejects_missing_metadata() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))
    response = client.put(
        "/v1/missions/sitl-1/qgroundcontrol",
        json={"plan": {"fileType": "Plan", "mission": {"items": []}}},
    )

    assert response.status_code == 422


def test_qgroundcontrol_plan_endpoint_validates_metadata_types_and_order() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))
    plan = {"fileType": "Plan", "mission": {"items": []}}
    missing_timestamp = client.put(
        "/v1/missions/sitl-1/qgroundcontrol",
        json={"valid_until": datetime.now(timezone.utc).isoformat(), "plan": plan},
    )
    assert missing_timestamp.status_code == 422

    now = datetime.now(timezone.utc)
    reversed_window = client.put(
        "/v1/missions/sitl-1/qgroundcontrol",
        json={
            "valid_from": (now + timedelta(minutes=30)).isoformat(),
            "valid_until": now.isoformat(),
            "plan": plan,
        },
    )
    assert reversed_window.status_code == 422


def test_onboard_mission_drift_is_reported_in_vehicle_status() -> None:
    app = create_app(ConnectorService(InMemoryBackend()))
    client = TestClient(app)
    submitted = _mission()
    assert client.put("/v1/missions/sitl-1", json=submitted).status_code == 200

    onboard = dict(submitted)
    onboard["source"] = "mavlink"
    response = client.put("/v1/vehicles/sitl-1/onboard-mission", json=onboard)

    assert response.status_code == 200
    assert response.json()["classification"] == "NON_OPERATIONAL_CHANGE"
    assert response.json()["submitted_mission_hash"] == response.json()["current_mission_hash"]


def test_onboard_mission_refresh_requires_a_configured_session() -> None:
    app = create_app(ConnectorService(InMemoryBackend()))
    client = TestClient(app)

    response = client.post("/v1/vehicles/sitl-1/onboard-mission/refresh")

    assert response.status_code == 409


def test_operation_refresh_reconciles_provider_state() -> None:
    service = ConnectorService(InMemoryBackend())
    client = TestClient(create_app(service))
    mission = _mission()
    assert client.put("/v1/missions/sitl-1", json=mission).status_code == 200
    operation_id = uuid4()
    created = client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"schema_version": "1.0", "command": "SUBMIT_OPERATION", "operation_id": str(operation_id)},
    )
    assert created.status_code == 201

    refreshed = client.post(f"/v1/operations/{operation_id}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["state"]["declaration"] == "ACCEPTED"


def test_completed_operation_is_terminal_and_not_active() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))
    assert client.put("/v1/missions/sitl-1", json=_mission()).status_code == 200
    operation_id = uuid4()
    assert client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"command": "SUBMIT_OPERATION", "operation_id": str(operation_id)},
    ).status_code == 201

    response = client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"command": "COMPLETE_OPERATION", "operation_id": str(operation_id)},
    )

    assert response.status_code == 201
    assert response.json()["state"]["declaration"] == "COMPLETED"
    assert client.get("/v1/health").json()["active_operations"] == 0
