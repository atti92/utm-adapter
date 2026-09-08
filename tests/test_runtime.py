from datetime import datetime, timezone
from threading import Event

from fastapi.testclient import TestClient

from utm_connector.api import create_app
from utm_connector.backends import InMemoryBackend
from utm_connector.config import ConnectorSettings, MavlinkConnectionConfig
from utm_connector.domain import (
    AltitudeDatum,
    Altitude,
    TelemetryQuality,
    VehicleConnectionState,
    VehicleHealth,
    VehicleIdentity,
    VehicleStateSnapshot,
    VehicleTelemetry,
)
from utm_connector.runtime import MavlinkSessionManager
from utm_connector.service import ConnectorService


class FakeSession:
    def __init__(self, snapshot: VehicleStateSnapshot) -> None:
        self._snapshot = snapshot
        self._sent = False

    def poll(self, timeout: float = 0.0) -> object:
        if self._sent:
            return None
        self._sent = True
        return object()

    def snapshot(self) -> VehicleStateSnapshot:
        return self._snapshot


def _snapshot() -> VehicleStateSnapshot:
    observed_at = datetime.now(timezone.utc)
    return VehicleStateSnapshot(
        identity=VehicleIdentity(
            connector_vehicle_id="sitl-1",
            mavlink_system_id=1,
            mavlink_component_ids=[1],
        ),
        connection_state=VehicleConnectionState.CONNECTED,
        telemetry=VehicleTelemetry(
            vehicle_id="sitl-1",
            observed_at=observed_at,
            latitude=47.5,
            longitude=19.0,
            altitude=Altitude(meters=20, datum=AltitudeDatum.AMSL),
            quality=TelemetryQuality.GOOD,
        ),
        quality=TelemetryQuality.GOOD,
        health=VehicleHealth(heartbeat_age_s=0, position_age_s=0),
    )


def test_configured_session_publishes_live_status() -> None:
    service = ConnectorService(InMemoryBackend())
    delivered = Event()
    snapshot = _snapshot()

    def on_snapshot(value: VehicleStateSnapshot) -> None:
        service.ingest_vehicle_snapshot(value)
        delivered.set()

    manager = MavlinkSessionManager(
        [MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udp:127.0.0.1:14550")],
        on_snapshot,
        poll_interval_s=0.01,
        session_factory=lambda _vehicle_id, _uri: FakeSession(snapshot),
    )
    app = create_app(service, ConnectorSettings(), manager)

    with TestClient(app) as client:
        assert delivered.wait(1)
        response = client.get("/v1/vehicles/sitl-1/status")

    assert response.status_code == 200
    assert response.json()["vehicle_state"]["connection_state"] == "CONNECTED"
    assert response.json()["latest_telemetry"]["latitude"] == 47.5
