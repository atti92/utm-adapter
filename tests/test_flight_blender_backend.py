import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from utm_connector.backends import BackendError, FlightBlenderBackend
from utm_connector.domain import AltitudeDatum, Mission, Operation, OperationState, VehicleTelemetry
from utm_connector.domain import OperationCommand
from utm_connector.recording import JsonlRecorder


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


def test_flight_blender_backend_submits_declaration_and_publishes_telemetry(tmp_path) -> None:
    requests: list[httpx.Request] = []
    provider_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("set_flight_declaration"):
            return httpx.Response(200, json={"id": provider_id, "message": "Submitted", "state": 1, "is_approved": 1})
        if request.url.path.endswith("flight_declaration_state/" + provider_id):
            return httpx.Response(200, json={"state": 2})
        return httpx.Response(201, json={"message": "Telemetry data successfully submitted"})

    recorder = JsonlRecorder(str(tmp_path / "connector-events.jsonl"))
    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        bearer_token="token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        recorder=recorder,
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
    assert operation.state.declaration.value == "ACCEPTED"
    assert operation.state.authorization.value == "AUTHORIZED"
    assert requests[0].url.path == "/flight_declaration_ops/set_flight_declaration"
    declaration = json.loads(requests[0].content)
    assert declaration["flight_declaration_geo_json"]["type"] == "FeatureCollection"
    assert declaration["flight_declaration_geo_json"]["features"][0]["geometry"]["type"] == "Polygon"
    assert requests[0].headers["authorization"] == "Bearer token"
    assert requests[1].url.path.endswith(provider_id)
    assert requests[2].url.path == "/flight_stream/set_telemetry"
    telemetry = json.loads(requests[2].content)
    assert telemetry["observations"][0]["flight_details"]["id"] == provider_id
    assert telemetry["observations"][0]["current_states"][0]["position"]["height"] is None
    assert "format" not in telemetry["observations"][0]["current_states"][0]["timestamp"]
    recorder.close()
    recorded = (tmp_path / "connector-events.jsonl").read_text()
    assert "Bearer token" not in recorded
    assert '"Authorization":"<redacted>"' in recorded


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


def test_flight_blender_backend_rejects_non_wgs84_telemetry() -> None:
    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )

    with pytest.raises(BackendError, match="telemetry requires WGS84"):
        backend.publish_telemetry(
            VehicleTelemetry(
                vehicle_id="sitl-1",
                observed_at=datetime.now(timezone.utc),
                latitude=47.4979,
                longitude=19.0402,
                altitude={"meters": 120, "datum": "AMSL"},
            )
        )


def test_flight_blender_backend_keeps_same_vehicle_operations_separate() -> None:
    requests: list[httpx.Request] = []
    provider_ids = iter(["provider-one", "provider-two"])

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("set_flight_declaration"):
            return httpx.Response(200, json={"id": next(provider_ids), "state": 1, "is_approved": 1})
        return httpx.Response(201, json={"message": "Telemetry data successfully submitted"})

    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    mission = _mission()
    first = backend.submit_operation(_operation(mission), mission)
    second = backend.submit_operation(_operation(mission), mission)
    telemetry = VehicleTelemetry(
        vehicle_id="sitl-1",
        observed_at=datetime.now(timezone.utc),
        latitude=47.4979,
        longitude=19.0402,
        altitude={"meters": 120, "datum": "WGS84"},
    )

    backend.publish_telemetry(telemetry, first)
    backend.publish_telemetry(telemetry, second)

    telemetry_requests = [request for request in requests if request.url.path.endswith("set_telemetry")]
    assert [json.loads(request.content)["observations"][0]["flight_details"]["id"] for request in telemetry_requests] == [
        "provider-one",
        "provider-two",
    ]


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


def test_flight_blender_backend_preserves_provider_validation_details() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "declaration window is in the past"})

    backend = FlightBlenderBackend(
        "http://flight-blender.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    mission = _mission()
    with pytest.raises(BackendError, match="declaration window is in the past"):
        backend.submit_operation(_operation(mission), mission)
