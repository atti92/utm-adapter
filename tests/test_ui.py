from fastapi.testclient import TestClient

from utm_connector.api import create_app
from utm_connector.backends import InMemoryBackend
from utm_connector.service import ConnectorService


def test_operator_console_is_served_without_external_assets() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))

    response = client.get("/ui/")

    assert response.status_code == 200
    assert "UTM Operator Console" in response.text
    assert "/ui/app.js" in response.text
    assert "/ui/styles.css" in response.text


def test_operator_console_contains_the_complete_gcs_workflow() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))

    html = client.get("/ui/").text
    javascript = client.get("/ui/app.js").text

    for label in ("Open mission file", "Check vehicle mission", "Validate &amp; save", "Submit to UTM", "Start operation", "Cancel", "Integration readiness", "operation-next-action", "Connection guide", "Copy diagnostics", "Support ID"):
        assert label in html
    for element_id in ("backend-readiness", "mavlink-readiness", "recording-readiness", "metrics-readiness", "altitude-readiness", "control-readiness"):
        assert element_id in html
    for endpoint in (
        "/v1/health",
        "/v1/vehicles",
        "/v1/missions/",
        "/v1/operator-intents",
        "/v1/operations/",
        "/v1/capabilities",
        "/v1/integration",
        "/v1/metrics",
        "/v1/vehicles/${encodeURIComponent(vehicleId)}/onboard-mission/refresh",
        "const onboardPath = `/v1/vehicles/${encodeURIComponent(vehicleId)}/onboard-mission`",
        "mission-planner",
    ):
        assert endpoint in javascript
    assert "formatDate(event.timestamp)" in javascript
    assert "buildPreviewMission" in javascript
    assert "function navigableMissionCommands()" in javascript
    assert "state.capabilities?.mission_commands" in javascript
    assert "DEFAULT_NAVIGABLE_MISSION_COMMANDS" in javascript
    assert "operator-console-preview" in javascript
    assert "renderMissionDrift" in javascript
    assert "renderMissionDrift(null);" in javascript
    assert "Vehicle mission matches the submitted route" in javascript
    assert "renderVehicleStatus" in javascript
    assert "metrics-readiness" in javascript
    assert "telemetryMetrics.published_total" in javascript
    assert '"X-Correlation-ID": correlationId' in javascript
    assert "$('correlation-id').textContent = correlationId" in javascript
    assert "battery_remaining_pct" in javascript
    assert "state.latestStatus?.latest_telemetry" in javascript
    assert "telemetry.altitude.datum" in javascript
    assert javascript.count('<div><span>Altitude</span>') == 1
    assert "altitude - 2" in javascript
    assert "clearVehicleWorkspace" in javascript
    assert "Validate & save the current mission before submitting it to UTM." in javascript
    assert "requires_future_start" in javascript
    assert "Mission settings changed. Validate & save before submitting." in javascript
    assert "windowCustomized" in javascript
    assert "if (!state.windowCustomized) setDefaultWindow()" in javascript
    assert '$("valid-from").value = localInputValue(new Date(mission.valid_from))' in javascript
    assert '$("valid-until").value = localInputValue(new Date(mission.valid_until))' in javascript
    assert '$("corridor-radius").value = mission.corridor_radius_m' in javascript
    assert 'state.windowCustomized = true;' in javascript
    assert 'command === "SUBMIT_OPERATION"' in javascript
    assert "TERMINAL_DECLARATIONS" in javascript
    assert "refreshInFlight" in javascript
    assert "missionReadInFlight" in javascript
    assert "const savedMission = Boolean(state.mission?.mission_hash" in javascript
    assert "Validate and save the mission before checking the vehicle's onboard route." in javascript
    assert "Validate & save the current mission before checking the vehicle mission." in javascript
    assert "intentInFlight" in javascript
    assert 'operation.state.telemetry_publication !== "NOT_STARTED"' in javascript
    assert 'state.latestStatus = null' in javascript
    assert "renderNextAction" in javascript
    assert "Operation is live and conforming." in javascript
    assert 'vehicle.connection_state === "LOST"' in javascript
    assert '["LOST", "INVALID"].includes(telemetry.quality)' in javascript
    assert 'health?.status !== "ok"' in javascript
    assert 'capabilities.mavlink?.non_commanding && capabilities.mavlink?.read_only' in javascript
    assert "The vehicle did not return a mission within 8 seconds." in javascript
    assert "Vehicle mission received" in javascript
    assert "GCS remains in control" in javascript
    assert "function renderSetupGuide" in javascript
    assert "One physical link can feed both GCS and connector" in javascript
    assert "function copyDiagnostics" in javascript
    assert 'geoid_grid_path: capabilities.altitude.geoid_conversion_configured ? "[configured]" : null' in javascript
    assert "correlation_id: correlationId" in javascript
    assert "navigator.clipboard.writeText" in javascript
    assert 'connectionState === "LOST"' in javascript
    assert '"STALE"' in javascript
    assert "function statusTone(value)" in javascript
    assert 'data-state="${statusTone(snapshot.connection_state)}"' in javascript
    assert 'data-state="${statusTone(snapshot.quality)}"' in javascript
    assert "The selected vehicle went offline" in javascript
    assert "The selected vehicle changed. Load a mission for the new vehicle." in javascript
    assert '$("plan-file").value = ""' in javascript
    assert "Load or create a mission for this vehicle." in javascript
    assert "replaceAll" not in javascript
    assert ".at(-1)" not in javascript
