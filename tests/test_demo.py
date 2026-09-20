from datetime import datetime, timezone

from utm_connector.backends import InMemoryBackend
from utm_connector.conformance import assess_conformance
from utm_connector.demo import DemoVehiclePublisher
from utm_connector.domain import AltitudeDatum, Mission, TelemetryQuality, VehicleTelemetry, Waypoint
from utm_connector.service import ConnectorService


def test_demo_publisher_uses_the_canonical_vehicle_snapshot_path() -> None:
    service = ConnectorService(InMemoryBackend())
    publisher = DemoVehiclePublisher(service, "demo-1")

    snapshot = publisher.publish_once(datetime(2030, 1, 1, tzinfo=timezone.utc))

    assert snapshot.identity.connector_vehicle_id == "demo-1"
    assert snapshot.connection_state.value == "CONNECTED"
    assert service.vehicles["demo-1"].quality.value == "GOOD"
    assert snapshot.telemetry.altitude.meters == 137
    assert snapshot.telemetry.altitude.datum.value == "WGS84"
    assert 47.49 < snapshot.telemetry.latitude < 47.51
    assert 19.03 < snapshot.telemetry.longitude < 19.05


def test_demo_route_stays_inside_the_built_in_mission_corridor() -> None:
    closed_route = (*DemoVehiclePublisher.DEMO_ROUTE, DemoVehiclePublisher.DEMO_ROUTE[0])
    mission = Mission(
        vehicle_id="demo-1",
        waypoints=[
            Waypoint(
                sequence=sequence,
                latitude=latitude,
                longitude=longitude,
                altitude={
                    "meters": 139 if sequence == 1 else 135,
                    "datum": AltitudeDatum.WGS84,
                },
            )
            for sequence, (latitude, longitude) in enumerate(closed_route)
        ],
        corridor_radius_m=30,
        valid_from=datetime(2030, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2030, 1, 1, 1, tzinfo=timezone.utc),
    )

    for segment_index, start in enumerate(closed_route[:-1]):
        end = closed_route[segment_index + 1]
        for step in range(11):
            fraction = step / 10
            telemetry = VehicleTelemetry(
                vehicle_id="demo-1",
                observed_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
                latitude=start[0] + (end[0] - start[0]) * fraction,
                longitude=start[1] + (end[1] - start[1]) * fraction,
                altitude={"meters": 137, "datum": AltitudeDatum.WGS84},
                quality=TelemetryQuality.GOOD,
            )
            assert assess_conformance(mission, telemetry).state.value == "CONFORMING"
