from datetime import datetime, timedelta, timezone
from uuid import uuid4

import json

import httpx
import pytest

from utm_connector.backends import BackendError, FlightBlenderBackend
from utm_connector.backends import InMemoryBackend
from utm_connector.domain import (
    Altitude,
    AltitudeDatum,
    ConformanceState,
    Mission,
    MissionSnapshot,
    Operation,
    OperationCommand,
    OperationIntent,
    TelemetryQuality,
    TelemetryPublicationState,
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


def _mission(start: datetime | None = None) -> Mission:
    start = start or datetime.now(timezone.utc)
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
        quality=TelemetryQuality.GOOD,
    )
    service.put_telemetry("sitl-1", telemetry)

    assert [operation.operation_id for operation in backend.published_operations] == operation_ids
    assert all(
        service.operations[operation_id].state.telemetry_publication.value == "ACTIVE"
        for operation_id in operation_ids
    )


def test_service_waits_for_scheduled_mission_window_without_provider_error() -> None:
    backend = OperationAwareBackend()
    service = ConnectorService(backend)
    service.put_mission("sitl-1", _mission(datetime.now(timezone.utc) + timedelta(seconds=30)))
    operation_id = uuid4()
    service.submit_operation(
        OperationIntent(operation_id=operation_id, command=OperationCommand.SUBMIT_OPERATION),
        "sitl-1",
    )
    service.apply_intent(
        OperationIntent(operation_id=operation_id, command=OperationCommand.START_OPERATION)
    )

    service.put_telemetry(
        "sitl-1",
        VehicleTelemetry(
            vehicle_id="sitl-1",
            observed_at=datetime.now(timezone.utc),
            latitude=47.4984,
            longitude=19.0407,
            altitude=Altitude(meters=122, datum=AltitudeDatum.AMSL),
            quality=TelemetryQuality.GOOD,
        ),
    )

    operation = service.operations[operation_id]
    assert backend.published_operations == []
    assert operation.state.telemetry_publication == TelemetryPublicationState.DEGRADED
    assert service.last_backend_error is None
    assert service.events[-1].event_type == "TELEMETRY_PUBLICATION_WITHHELD"
    assert service.events[-1].details["reason"] == "mission window has not opened"


def test_service_retries_transient_provider_telemetry_failures() -> None:
    class TransientBackend(OperationAwareBackend):
        failures_remaining = 1

        def publish_telemetry(self, telemetry: VehicleTelemetry, operation: Operation | None = None) -> None:
            if self.failures_remaining:
                self.failures_remaining -= 1
                raise BackendError("provider is not active yet")
            super().publish_telemetry(telemetry, operation)

    backend = TransientBackend()
    service = ConnectorService(backend)
    service.put_mission("sitl-1", _mission())
    operation_id = uuid4()
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
        latitude=47.4984,
        longitude=19.0407,
        altitude=Altitude(meters=122, datum=AltitudeDatum.AMSL),
        quality=TelemetryQuality.GOOD,
    )

    with pytest.raises(BackendError, match="not active yet"):
        service.put_telemetry("sitl-1", telemetry)
    assert service.operations[operation_id].state.telemetry_publication == TelemetryPublicationState.DEGRADED

    service.put_telemetry("sitl-1", telemetry)
    assert service.operations[operation_id].state.telemetry_publication == TelemetryPublicationState.ACTIVE
    assert len(backend.telemetry) == 1


def test_service_withholds_stale_telemetry_from_provider() -> None:
    backend = OperationAwareBackend()
    service = ConnectorService(backend)
    service.put_mission("sitl-1", _mission())
    operation_id = uuid4()
    service.submit_operation(
        OperationIntent(operation_id=operation_id, command=OperationCommand.SUBMIT_OPERATION),
        "sitl-1",
    )
    service.apply_intent(
        OperationIntent(operation_id=operation_id, command=OperationCommand.START_OPERATION)
    )

    service.put_telemetry(
        "sitl-1",
        VehicleTelemetry(
            vehicle_id="sitl-1",
            observed_at=datetime.now(timezone.utc) - timedelta(seconds=20),
            latitude=47.4984,
            longitude=19.0407,
            altitude=Altitude(meters=122, datum=AltitudeDatum.AMSL),
            quality=TelemetryQuality.LOST,
        ),
    )

    operation = service.operations[operation_id]
    assert backend.published_operations == []
    assert operation.state.telemetry_publication == TelemetryPublicationState.DEGRADED
    assert operation.state.conformance == ConformanceState.TELEMETRY_UNRELIABLE
    assert service.events[-1].event_type == "TELEMETRY_PUBLICATION_WITHHELD"


def test_service_coalesces_provider_telemetry_at_configured_rate() -> None:
    backend = OperationAwareBackend()
    service = ConnectorService(backend, telemetry_publish_interval_s=60)
    service.put_mission("sitl-1", _mission())
    operation_id = uuid4()
    service.submit_operation(
        OperationIntent(operation_id=operation_id, command=OperationCommand.SUBMIT_OPERATION),
        "sitl-1",
    )
    service.apply_intent(
        OperationIntent(operation_id=operation_id, command=OperationCommand.START_OPERATION)
    )

    def telemetry() -> VehicleTelemetry:
        return VehicleTelemetry(
            vehicle_id="sitl-1",
            observed_at=datetime.now(timezone.utc),
            latitude=47.4984,
            longitude=19.0407,
            altitude=Altitude(meters=122, datum=AltitudeDatum.AMSL),
            quality=TelemetryQuality.GOOD,
        )

    service.put_telemetry("sitl-1", telemetry())
    service.put_telemetry("sitl-1", telemetry())

    assert len(backend.published_operations) == 1
    assert service.operations[operation_id].state.telemetry_publication == TelemetryPublicationState.ACTIVE


def test_service_coalesces_repeated_conformance_events_without_skipping_assessment() -> None:
    backend = OperationAwareBackend()
    service = ConnectorService(backend, event_coalesce_interval_s=60)
    service.put_mission("sitl-1", _mission())
    operation_id = uuid4()
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
        quality=TelemetryQuality.GOOD,
    )
    service.put_telemetry("sitl-1", telemetry)
    service.put_telemetry("sitl-1", telemetry.model_copy(update={"observed_at": datetime.now(timezone.utc)}))

    conformance_events = [event for event in service.events if event.event_type == "CONFORMANCE_ASSESSED"]
    assert len(conformance_events) == 1
    assert service.operations[operation_id].state.conformance == ConformanceState.CONFORMING


def test_service_coalesces_repeated_window_withheld_events() -> None:
    backend = OperationAwareBackend()
    service = ConnectorService(backend, event_coalesce_interval_s=60)
    service.put_mission("sitl-1", _mission(datetime.now(timezone.utc) + timedelta(minutes=5)))
    operation_id = uuid4()
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
        quality=TelemetryQuality.GOOD,
    )

    service.put_telemetry("sitl-1", telemetry)
    service.put_telemetry("sitl-1", telemetry.model_copy(update={"observed_at": datetime.now(timezone.utc)}))

    withheld_events = [
        event for event in service.events if event.event_type == "TELEMETRY_PUBLICATION_WITHHELD"
    ]
    assert len(withheld_events) == 1
    assert backend.published_operations == []


def test_service_converts_altitude_at_flight_blender_boundary() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("set_flight_declaration"):
            return httpx.Response(200, json={"id": "provider-1", "state": 1, "is_approved": 1})
        return httpx.Response(201, json={"message": "Telemetry data successfully submitted"})

    class OffsetConverter:
        @staticmethod
        def convert_mission(mission: Mission, *, target: AltitudeDatum) -> Mission:
            assert target == AltitudeDatum.WGS84
            return mission.model_copy(
                update={
                    "waypoints": [
                        waypoint.model_copy(
                            update={
                                "altitude": Altitude(
                                    meters=waypoint.altitude.meters + 100,
                                    datum=target,
                                )
                            }
                        )
                        for waypoint in mission.waypoints
                    ]
                }
            )

        @staticmethod
        def convert_telemetry(telemetry: VehicleTelemetry, *, target: AltitudeDatum) -> VehicleTelemetry:
            assert target == AltitudeDatum.WGS84
            return telemetry.model_copy(
                update={
                    "altitude": Altitude(
                        meters=telemetry.altitude.meters + 100,
                        datum=target,
                    )
                }
            )

    service = ConnectorService(
        FlightBlenderBackend(
            "http://flight-blender.test",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        altitude_converter=OffsetConverter(),  # type: ignore[arg-type]
    )
    mission = _mission(datetime.now(timezone.utc) + timedelta(minutes=5))
    service.put_mission("sitl-1", mission)
    operation_id = uuid4()
    service.submit_operation(
        OperationIntent(operation_id=operation_id, command=OperationCommand.SUBMIT_OPERATION),
        "sitl-1",
    )
    service.apply_intent(
        OperationIntent(operation_id=operation_id, command=OperationCommand.START_OPERATION)
    )
    # The provider preflight intentionally requires a future declaration, but
    # this test exercises immediate telemetry conversion after the operation
    # has started. Move the local snapshot into its active window explicitly.
    active_mission = mission.model_copy(
        update={"valid_from": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    service.missions["sitl-1"] = MissionSnapshot(
        mission=active_mission,
        mission_hash=active_mission.canonical_hash(),
    )

    service.put_telemetry(
        "sitl-1",
        VehicleTelemetry(
            vehicle_id="sitl-1",
            observed_at=datetime.now(timezone.utc),
            latitude=47.4984,
            longitude=19.0407,
            altitude=Altitude(meters=122, datum=AltitudeDatum.AMSL),
            quality="GOOD",
        ),
    )

    declaration = json.loads(requests[0].content)
    telemetry = json.loads(requests[2].content)
    min_altitude = declaration["flight_declaration_geo_json"]["features"][0]["properties"]["min_altitude"]
    observed_altitude = telemetry["observations"][0]["current_states"][0]["position"]["alt"]
    assert min_altitude == {"meters": 220.0, "datum": "WGS84"}
    assert observed_altitude == 222.0
    assert service.operations[operation_id].state.conformance.value == "CONFORMING"
    assert service.operations[operation_id].state.telemetry_publication.value == "ACTIVE"


def test_service_marks_provider_publication_unreliable_without_altitude_conversion() -> None:
    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"id": "provider-1", "state": 1, "is_approved": 1},
                )
                if request.url.path.endswith("set_flight_declaration")
                else httpx.Response(201),
            )
        ),
    )
    service = ConnectorService(backend)
    service.put_mission("sitl-1", _mission())

    with pytest.raises(BackendError, match="requires WGS84 mission altitude"):
        service.submit_operation(
            OperationIntent(operation_id=uuid4(), command=OperationCommand.SUBMIT_OPERATION),
            "sitl-1",
        )
