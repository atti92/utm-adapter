from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from utm_connector.api import create_app
from utm_connector.backends import InMemoryBackend
from utm_connector.config import ConnectorSettings, MavlinkConnectionConfig
from utm_connector.runtime import MavlinkSessionManager
from utm_connector.persistence import SQLiteStateStore
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
    app = create_app(
        ConnectorService(InMemoryBackend()),
        ConnectorSettings(mavlink_connections=[]),
    )
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
    metrics = client.get("/v1/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["telemetry"]["received_total"] == 1
    assert metrics.json()["telemetry"]["published_total"] == 1
    assert metrics.json()["telemetry"]["queue_depth"] == 0
    assert metrics.json()["vehicles"] == {"active": 1, "configured": 0, "session_errors": 0}
    assert metrics.json()["operations"]["active"] == 1
    assert len(client.get("/v1/events").json()) >= 5


def test_default_app_closes_owned_state_store_on_shutdown(tmp_path) -> None:
    state_store = SQLiteStateStore(str(tmp_path / "state.sqlite3"))
    settings = ConnectorSettings(state_db_path=str(tmp_path / "state.sqlite3"))

    with patch("utm_connector.api.SQLiteStateStore", return_value=state_store):
        with TestClient(create_app(settings=settings)) as client:
            assert client.get("/v1/health").status_code == 200

    assert state_store._closed is True


def test_default_app_wires_downloaded_missions_into_service() -> None:
    service = ConnectorService(InMemoryBackend())
    app = create_app(service, ConnectorSettings(mavlink_connections=[]))

    assert app.state.mavlink_session_manager.on_mission == service.ingest_onboard_mission


def test_health_exposes_provider_failure_and_recovery() -> None:
    service = ConnectorService(InMemoryBackend())
    with TestClient(create_app(service, ConnectorSettings(mavlink_connections=[]))) as client:
        service.record_backend_error("provider unavailable")
        degraded = client.get("/v1/health")
        assert degraded.json()["status"] == "degraded"
        assert degraded.json()["backend_error"] == "provider unavailable"

        service.mark_backend_healthy()
        recovered = client.get("/v1/health")
        assert recovered.json()["status"] == "ok"
        assert recovered.json()["backend_error"] is None


def test_api_returns_a_correlation_id_for_gcs_support_logs() -> None:
    correlation_id = str(uuid4())
    with TestClient(
        create_app(
            ConnectorService(InMemoryBackend()),
            ConnectorSettings(mavlink_connections=[]),
        )
    ) as client:
        forwarded = client.get("/v1/health", headers={"X-Correlation-ID": correlation_id})
        generated = client.get("/v1/health", headers={"X-Correlation-ID": "not-a-uuid"})

    assert forwarded.headers["x-correlation-id"] == correlation_id
    assert UUID(generated.headers["x-correlation-id"])


def test_capabilities_and_vehicle_directory_are_gcs_friendly() -> None:
    client = TestClient(
        create_app(
            ConnectorService(InMemoryBackend()),
            ConnectorSettings(mavlink_connections=[]),
        )
    )
    capabilities = client.get("/v1/capabilities")

    assert capabilities.status_code == 200
    assert capabilities.json()["integration_manifest"] == "/v1/integration"
    assert capabilities.json()["recording"] == {"configured": False, "mavlink_raw": False}
    assert capabilities.json()["mavlink"] == {
        "configured": False,
        "non_commanding": True,
        "read_only": True,
        "mission_download": True,
        "recommended_topology": "single_router_endpoint",
        "telemetry_publish_interval_s": 1.0,
        "reconnect_interval_s": 5.0,
        "event_coalesce_interval_s": 5.0,
    }
    assert capabilities.json()["mission_window"] == {
        "requires_future_start": False,
        "max_future_seconds": None,
    }
    assert capabilities.json()["mission_commands"] == [
        {"command": 16, "name": "WAYPOINT", "role": "route_point"},
        {"command": 21, "name": "LAND", "role": "route_endpoint"},
        {"command": 22, "name": "TAKEOFF", "role": "route_point"},
    ]
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


def test_recording_capability_is_discoverable_when_configured(tmp_path) -> None:
    settings = ConnectorSettings(
        state_db_path=str(tmp_path / "state.sqlite3"),
        record_path=str(tmp_path / "connector-events.jsonl"),
    )
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/v1/capabilities").json()["recording"] == {
            "configured": True,
            "mavlink_raw": True,
        }


def test_root_launches_operator_console_and_exposes_integration_contract() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))

    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/ui/"

    manifest = client.get("/v1/integration")
    assert manifest.status_code == 200
    payload = manifest.json()
    assert payload["operator_console"]["path"] == "/ui/"
    assert payload["api"]["metrics_path"] == "/v1/metrics"
    assert payload["api"]["mission"]["qgroundcontrol"] == {
        "method": "PUT",
        "path": "/v1/missions/{vehicle_id}/qgroundcontrol",
    }
    assert payload["api"]["mission"]["mission_planner"] == {
        "method": "PUT",
        "path": "/v1/missions/{vehicle_id}/mission-planner",
    }
    assert payload["mavlink"]["vehicle_control"] == "none"


def test_metrics_are_available_before_any_traffic() -> None:
    with TestClient(
        create_app(
            ConnectorService(InMemoryBackend()),
            ConnectorSettings(mavlink_connections=[]),
        )
    ) as client:
        payload = client.get("/v1/metrics").json()

    assert payload["uptime_s"] >= 0
    assert payload["started_at"]
    assert payload["telemetry"] == {
        "received_total": 0,
        "published_total": 0,
        "withheld_total": 0,
        "failed_total": 0,
        "last_received_at": None,
        "last_published_at": None,
        "queue_depth": 0,
    }
    assert payload["backend"]["requests_total"] == 0
    assert payload["backend"]["errors_total"] == 0
    assert payload["vehicles"] == {"active": 0, "configured": 0, "session_errors": 0}
    assert payload["operations"] == {"active": 0, "known": 0}


def test_opt_in_demo_mode_publishes_a_vehicle_for_the_operator_console() -> None:
    service = ConnectorService(InMemoryBackend())
    settings = ConnectorSettings(
        state_db_path=":memory:",
        demo_mode=True,
        demo_vehicle_id="demo-1",
        mavlink_connections=[],
    )

    with TestClient(create_app(service, settings=settings)) as client:
        vehicle = client.get("/v1/vehicles")
        assert vehicle.status_code == 200
        assert vehicle.json()[0]["vehicle_id"] == "demo-1"
        assert vehicle.json()[0]["connection_state"] == "CONNECTED"
        assert client.get("/v1/capabilities").json()["demo_mode"] is True
        status = client.get("/v1/vehicles/demo-1/status")
        assert status.status_code == 200
        assert status.json()["latest_telemetry"]["quality"] == "GOOD"


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


def test_submitted_mission_can_be_reloaded_by_operator_console() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))
    payload = _mission()

    assert client.put("/v1/missions/sitl-1", json=payload).status_code == 200
    response = client.get("/v1/missions/sitl-1")

    assert response.status_code == 200
    assert response.json()["mission"]["vehicle_id"] == "sitl-1"
    assert response.json()["mission_hash"]
    assert client.get("/v1/missions/unknown").status_code == 404


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


def test_mission_planner_plan_endpoint_normalizes_wpl_text() -> None:
    app = create_app(ConnectorService(InMemoryBackend()))
    client = TestClient(app)
    now = datetime.now(timezone.utc)
    response = client.put(
        "/v1/missions/sitl-1/mission-planner",
        json={
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(minutes=30)).isoformat(),
            "text": "QGC WPL 110\n"
            "0 1 3 22 0 0 0 0 47.5 19.0 20 1\n"
            "1 0 3 16 0 0 0 0 47.501 19.001 25 1",
        },
    )

    assert response.status_code == 200
    assert response.json()["mission"]["source"] == "mission-planner"


def test_mission_planner_plan_endpoint_rejects_invalid_text() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))
    now = datetime.now(timezone.utc)
    response = client.put(
        "/v1/missions/sitl-1/mission-planner",
        json={
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(minutes=30)).isoformat(),
            "text": "not a waypoint file",
        },
    )

    assert response.status_code == 422


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
    stored = client.get("/v1/vehicles/sitl-1/onboard-mission")
    assert stored.status_code == 200
    assert stored.json()["mission"]["source"] == "mavlink"


def test_onboard_mission_get_reports_missing_snapshot() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))

    response = client.get("/v1/vehicles/sitl-1/onboard-mission")

    assert response.status_code == 404


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

    cancel = client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"command": "CANCEL_OPERATION", "operation_id": str(operation_id)},
    )
    assert cancel.status_code == 409
    assert cancel.json()["detail"] == "operation is terminal and cannot be cancelled"


def test_start_command_cannot_be_repeated_after_publication_begins() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))
    assert client.put("/v1/missions/sitl-1", json=_mission()).status_code == 200
    operation_id = str(uuid4())
    assert client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"command": "SUBMIT_OPERATION", "operation_id": operation_id},
    ).status_code == 201
    assert client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"command": "START_OPERATION", "operation_id": operation_id},
    ).status_code == 201

    repeated = client.post(
        "/v1/operator-intents?vehicle_id=sitl-1",
        json={"command": "START_OPERATION", "operation_id": operation_id},
    )

    assert repeated.status_code == 409
    assert repeated.json()["detail"] == "operation has already started"
