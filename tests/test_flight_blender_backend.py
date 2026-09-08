import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from utm_connector.backends import BackendError, FlightBlenderBackend
from utm_connector.domain import AltitudeDatum, Mission, Operation, OperationState, VehicleTelemetry
from utm_connector.domain import OperationCommand


def _mission(datum: AltitudeDatum = AltitudeDatum.WGS84) -> Mission:
    start = datetime.now(timezone.utc) + timedelta(minutes=10)
    return Mission(
        vehicle_id="sitl-1",
        valid_from=start,
        valid_until=start + timedelta(minutes=20),
        waypoints=[
            {"sequence": 0, "latitude": 47.4979, "longitude": 19.0402, "altitude": {"meters": 120, "datum": datum}},
            {"sequence": 1, "latitude": 47.4989, "longitude": 19.0412, "altitude": {"meters": 125, "datum": datum}},
        ],
    )


def _operation(mission: Mission) -> Operation:
    return Operation(
        operation_id=uuid4(),
        vehicle_id=mission.vehicle_id,
        mission_id=mission.mission_id,
        mission_hash=mission.canonical_hash(),
        state=OperationState(),
    )


def test_flight_blender_backend_submits_declaration_and_publishes_telemetry() -> None:
    requests: list[httpx.Request] = []
    provider_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("set_flight_declaration"):
            return httpx.Response(200, json={"id": provider_id, "message": "Submitted"})
        if request.url.path.endswith("flight_declaration_state/" + provider_id):
            return httpx.Response(200, json={"state": 2})
        return httpx.Response(201, json={"message": "Telemetry data successfully submitted"})

    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        bearer_token="token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    mission = _mission()
    operation = backend.submit_operation(_operation(mission), mission)
    backend.update_operation(operation, OperationCommand.START_OPERATION)
    backend.publish_telemetry(
        VehicleTelemetry(
            vehicle_id="sitl-1",
            observed_at=datetime.now(timezone.utc),
            latitude=47.4979,
            longitude=19.0402,
            altitude={"meters": 120, "datum": "WGS84"},
            heading_deg=90,
            groundspeed_mps=4,
        )
    )

    assert operation.provider_operation_id == provider_id
    assert requests[0].url.path == "/flight_declaration_ops/set_flight_declaration"
    declaration = json.loads(requests[0].content)
    assert declaration["flight_declaration_geo_json"]["type"] == "FeatureCollection"
    assert declaration["flight_declaration_geo_json"]["features"][0]["geometry"]["type"] == "Polygon"
    assert requests[0].headers["authorization"] == "Bearer token"
    assert requests[1].url.path.endswith(provider_id)
    assert requests[2].url.path == "/flight_stream/set_telemetry"
    telemetry = json.loads(requests[2].content)
    assert telemetry["observations"][0]["flight_details"]["id"] == provider_id


def test_flight_blender_backend_rejects_non_wgs84_declaration_altitude() -> None:
    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    mission = _mission(AltitudeDatum.AGL)

    with pytest.raises(BackendError, match="WGS84"):
        backend.submit_operation(_operation(mission), mission)


def test_flight_blender_backend_requires_operation_for_telemetry() -> None:
    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )

    with pytest.raises(BackendError, match="no submitted operation"):
        backend.publish_telemetry(
            VehicleTelemetry(
                vehicle_id="sitl-1",
                observed_at=datetime.now(timezone.utc),
                latitude=47.4979,
                longitude=19.0402,
                altitude={"meters": 120, "datum": "WGS84"},
            )
        )


def test_flight_blender_backend_retries_transient_provider_failure() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"message": "temporary outage"})
        return httpx.Response(200, json={"id": str(uuid4())})

    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        max_retries=2,
        retry_backoff_s=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    mission = _mission()

    backend.submit_operation(_operation(mission), mission)

    assert attempts == 3
