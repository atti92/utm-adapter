from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from utm_connector.backends import FlightBlenderBackend
from utm_connector.backends import InMemoryBackend
from utm_connector.domain import (
    Altitude,
    AltitudeDatum,
    Mission,
    Operation,
    OperationCommand,
    OperationIntent,
    VehicleTelemetry,
)
from utm_connector.service import ConnectorService


class OperationAwareBackend(InMemoryBackend):
    def __init__(self) -> None:
        super().__init__()
        self.published_operations: list[Operation] = []

    def publish_telemetry(self, telemetry: VehicleTelemetry, operation: Operation | None = None) -> None:
        assert operation is not None
        self.published_operations.append(operation)
        super().publish_telemetry(telemetry, operation)


def _mission() -> Mission:
    start = datetime.now(timezone.utc)
    return Mission(
        vehicle_id="sitl-1",
        valid_from=start,
        valid_until=start + timedelta(hours=1),
        waypoints=[
            {"sequence": 0, "latitude": 47.4979, "longitude": 19.0402, "altitude": {"meters": 120, "datum": "AMSL"}},
            {"sequence": 1, "latitude": 47.4989, "longitude": 19.0412, "altitude": {"meters": 125, "datum": "AMSL"}},
        ],
    )


def test_flight_blender_backend_keeps_pre_operation_telemetry_local() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    service = ConnectorService(
        FlightBlenderBackend(
            "http://flight-blender.test",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )
    telemetry = VehicleTelemetry(
        vehicle_id="sitl-1",
        observed_at=datetime.now(timezone.utc),
        latitude=47.5,
        longitude=19.0,
        altitude=Altitude(meters=100, datum=AltitudeDatum.AMSL),
    )

    assert service.put_telemetry("sitl-1", telemetry) == telemetry
    assert service.vehicles["sitl-1"] == telemetry
    assert requests == []
    assert service.events[-1].event_type == "TELEMETRY_RECEIVED"


def test_service_publishes_one_telemetry_observation_per_active_operation() -> None:
    backend = OperationAwareBackend()
    service = ConnectorService(backend)
    service.put_mission("sitl-1", _mission())

    operation_ids = [uuid4(), uuid4()]
    for operation_id in operation_ids:
        service.submit_operation(
            OperationIntent(operation_id=operation_id, command=OperationCommand.SUBMIT_OPERATION),
            "sitl-1",
        )
        service.apply_intent(
            OperationIntent(operation_id=operation_id, command=OperationCommand.START_OPERATION)
        )

    telemetry = VehicleTelemetry(
        vehicle_id="sitl-1",
        observed_at=datetime.now(timezone.utc),
        latitude=47.4979,
        longitude=19.0402,
        altitude=Altitude(meters=120, datum=AltitudeDatum.AMSL),
    )
    service.put_telemetry("sitl-1", telemetry)

    assert [operation.operation_id for operation in backend.published_operations] == operation_ids
    assert all(
        service.operations[operation_id].state.telemetry_publication.value == "ACTIVE"
        for operation_id in operation_ids
    )
