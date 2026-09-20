from datetime import datetime, timedelta, timezone
from threading import Event
from time import sleep
from uuid import uuid4

from fastapi.testclient import TestClient

from utm_connector.api import create_app
from utm_connector.backends import BackendError, InMemoryBackend
from utm_connector.config import ConnectorSettings, MavlinkConnectionConfig
from utm_connector.domain import (
    AltitudeDatum,
    Altitude,
    Mission,
    OperationCommand,
    OperationIntent,
    TelemetryQuality,
    VehicleConnectionState,
    VehicleHealth,
    VehicleIdentity,
    VehicleStateSnapshot,
    VehicleTelemetry,
)
from utm_connector.mission_reader import MavlinkMissionRead
from utm_connector.runtime import MavlinkSessionManager
from utm_connector.service import ConnectorService


class FakeSession:
    def __init__(self, snapshot: VehicleStateSnapshot) -> None:
        self._snapshot = snapshot
        self._sent = False
        self.closed = False

    def poll(self, timeout: float = 0.0) -> object:
        if self._sent:
            return None
        self._sent = True
        return object()

    def snapshot(self) -> VehicleStateSnapshot:
        return self._snapshot

    @property
    def onboard_mission(self) -> MavlinkMissionRead | None:
        return None

    def request_mission(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


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


def test_provider_failure_does_not_make_mavlink_session_look_disconnected() -> None:
    class FailingProvider(InMemoryBackend):
        def publish_telemetry(self, telemetry, operation=None) -> None:
            raise BackendError("provider temporarily unavailable")

    service = ConnectorService(FailingProvider())
    now = datetime.now(timezone.utc)
    service.put_mission(
        "sitl-1",
        Mission(
            vehicle_id="sitl-1",
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(minutes=30),
            waypoints=[
                {
                    "sequence": 0,
                    "latitude": 47.5,
                    "longitude": 19.0,
                    "altitude": {"meters": 20, "datum": "AMSL"},
                },
                {
                    "sequence": 1,
                    "latitude": 47.501,
                    "longitude": 19.001,
                    "altitude": {"meters": 25, "datum": "AMSL"},
                },
            ],
        ),
    )
    operation_id = uuid4()
    service.submit_operation(
        OperationIntent(operation_id=operation_id, command=OperationCommand.SUBMIT_OPERATION),
        "sitl-1",
    )
    service.apply_intent(
        OperationIntent(operation_id=operation_id, command=OperationCommand.START_OPERATION)
    )

    created: list[FakeSession] = []
    delivered = Event()

    def factory(_vehicle_id: str, _uri: str) -> FakeSession:
        session = FakeSession(_snapshot())
        created.append(session)
        return session

    def on_snapshot(snapshot: VehicleStateSnapshot) -> None:
        service.ingest_vehicle_snapshot(snapshot)
        delivered.set()

    manager = MavlinkSessionManager(
        [MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udp:127.0.0.1:14550")],
        on_snapshot,
        poll_interval_s=0.01,
        reconnect_interval_s=0.01,
        session_factory=factory,
    )
    manager.start()
    assert delivered.wait(1)
    sleep(0.05)
    manager.stop()

    assert len(created) == 1
    assert manager.last_errors == {}
    assert service.last_backend_error == "provider temporarily unavailable"
    assert service.vehicle_snapshots["sitl-1"].connection_state == VehicleConnectionState.CONNECTED


def test_session_manager_closes_sessions_and_can_restart() -> None:
    service = ConnectorService(InMemoryBackend())
    sessions: list[FakeSession] = []

    def factory(_vehicle_id: str, _uri: str) -> FakeSession:
        session = FakeSession(_snapshot())
        sessions.append(session)
        return session

    manager = MavlinkSessionManager(
        [MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udp:127.0.0.1:14550")],
        lambda snapshot: service.ingest_vehicle_snapshot(snapshot),
        poll_interval_s=0.01,
        session_factory=factory,
    )
    manager.start()
    manager.stop()

    assert sessions[0].closed is True
    assert manager.sessions == {}

    manager.start()
    manager.stop()
    assert len(sessions) == 2
    assert sessions[1].closed is True


def test_session_manager_keeps_last_connection_error_for_diagnostics() -> None:
    errors: list[tuple[str, str]] = []

    def factory(_vehicle_id: str, _uri: str) -> FakeSession:
        raise RuntimeError("simulator is offline")

    manager = MavlinkSessionManager(
        [MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udp:127.0.0.1:14550")],
        lambda _snapshot: None,
        session_factory=factory,
        on_error=lambda vehicle_id, error: errors.append((vehicle_id, str(error))),
    )
    manager.start()

    assert manager.last_errors == {"sitl-1": "simulator is offline"}
    assert errors == [("sitl-1", "simulator is offline")]
    manager.stop()


def test_session_manager_reconnects_after_link_failure() -> None:
    delivered = Event()
    created: list[FakeSession] = []

    class BrokenSession(FakeSession):
        def poll(self, timeout: float = 0.0) -> object:
            raise RuntimeError("vehicle link dropped")

    def factory(_vehicle_id: str, _uri: str) -> FakeSession:
        session = BrokenSession(_snapshot()) if not created else FakeSession(_snapshot())
        created.append(session)
        return session

    manager = MavlinkSessionManager(
        [MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udpin:127.0.0.1:14551")],
        lambda _snapshot: delivered.set(),
        poll_interval_s=0.01,
        reconnect_interval_s=0.01,
        session_factory=factory,
    )
    manager.start()

    assert delivered.wait(1)
    manager.stop()

    assert len(created) >= 2
    assert created[0].closed is True
    assert manager.last_errors == {}


def test_session_manager_retries_an_unavailable_link() -> None:
    delivered = Event()
    attempts = 0

    def factory(_vehicle_id: str, _uri: str) -> FakeSession:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("vehicle is offline")
        return FakeSession(_snapshot())

    manager = MavlinkSessionManager(
        [MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udpin:127.0.0.1:14551")],
        lambda _snapshot: delivered.set(),
        poll_interval_s=0.01,
        reconnect_interval_s=0.01,
        session_factory=factory,
    )
    manager.start()

    assert delivered.wait(1)
    manager.stop()

    assert attempts >= 2
    assert manager.last_errors == {}


def test_session_manager_delivers_quiet_period_connection_transitions() -> None:
    connected = _snapshot()
    lost = connected.model_copy(
        update={
            "connection_state": VehicleConnectionState.LOST,
            "quality": TelemetryQuality.LOST,
            "telemetry": connected.telemetry.model_copy(update={"quality": TelemetryQuality.LOST}),
            "health": VehicleHealth(heartbeat_age_s=11, position_age_s=11),
        }
    )

    class QuietSession:
        def __init__(self) -> None:
            self.calls = 0

        def poll(self, timeout: float = 0.0) -> object:
            return None

        def snapshot(self) -> VehicleStateSnapshot:
            self.calls += 1
            return connected if self.calls == 1 else lost

        @property
        def onboard_mission(self) -> MavlinkMissionRead | None:
            return None

        def request_mission(self) -> None:
            return None

        def close(self) -> None:
            return None

    received: list[VehicleStateSnapshot] = []
    manager = MavlinkSessionManager(
        [],
        received.append,
        session_factory=lambda _vehicle_id, _uri: QuietSession(),
    )
    manager.sessions["sitl-1"] = QuietSession()

    manager.poll_once()
    manager.poll_once()
    manager.poll_once()

    assert [snapshot.connection_state for snapshot in received] == [
        VehicleConnectionState.CONNECTED,
        VehicleConnectionState.LOST,
    ]
