from datetime import datetime, timezone

import httpx

from utm_connector.backends import FlightBlenderBackend
from utm_connector.domain import Altitude, AltitudeDatum, VehicleTelemetry
from utm_connector.service import ConnectorService


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
