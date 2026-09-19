from datetime import datetime, timezone

from utm_connector.backends import InMemoryBackend
from utm_connector.demo import DemoVehiclePublisher
from utm_connector.service import ConnectorService


def test_demo_publisher_uses_the_canonical_vehicle_snapshot_path() -> None:
    service = ConnectorService(InMemoryBackend())
    publisher = DemoVehiclePublisher(service, "demo-1")

    snapshot = publisher.publish_once(datetime(2030, 1, 1, tzinfo=timezone.utc))

    assert snapshot.identity.connector_vehicle_id == "demo-1"
    assert snapshot.connection_state.value == "CONNECTED"
    assert service.vehicles["demo-1"].quality.value == "GOOD"
    assert 47.49 < snapshot.telemetry.latitude < 47.51
    assert 19.03 < snapshot.telemetry.longitude < 19.05
