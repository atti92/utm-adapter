from datetime import datetime, timedelta, timezone
from uuid import uuid4

from utm_connector.backends import InMemoryBackend
from utm_connector.domain import Altitude, AltitudeDatum, Mission, OperationCommand, OperationIntent, VehicleTelemetry
from utm_connector.persistence import SQLiteStateStore
from utm_connector.service import ConnectorService


def _mission() -> Mission:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Mission(
        vehicle_id="sitl-1",
        valid_from=start,
        valid_until=start + timedelta(minutes=30),
        source="test",
        waypoints=[
            {"sequence": 0, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 20, "datum": "AGL"}},
            {"sequence": 1, "latitude": 47.501, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
        ],
    )


def test_connector_state_survives_service_restart(tmp_path) -> None:
    store = SQLiteStateStore(str(tmp_path / "state.sqlite3"))
    first = ConnectorService(InMemoryBackend(), store)
    first.put_mission("sitl-1", _mission())
    operation_id = uuid4()
    first.submit_operation(
        OperationIntent(operation_id=operation_id, command=OperationCommand.SUBMIT_OPERATION)
        , "sitl-1",
    )
    first.put_telemetry(
        "sitl-1",
        VehicleTelemetry(
            vehicle_id="sitl-1",
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            latitude=47.5,
            longitude=19.0,
            altitude=Altitude(meters=20, datum=AltitudeDatum.AGL),
        ),
    )
    first.record_event("TEST_EVENT", vehicle_id="sitl-1")
    store.close()

    restarted_store = SQLiteStateStore(str(tmp_path / "state.sqlite3"))
    second = ConnectorService(InMemoryBackend(), restarted_store)

    assert "sitl-1" in second.missions
    assert operation_id in second.operations
    assert second.vehicles["sitl-1"].latitude == 47.5
    assert any(event.event_type == "TEST_EVENT" for event in second.events)
    restarted_store.close()
    restarted_store.close()
