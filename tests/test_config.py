import pytest
from pydantic import ValidationError

from utm_connector.config import ConnectorSettings, MavlinkConnectionConfig


def test_mavlink_vehicle_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="MAVLink vehicle_id values must be unique"):
        ConnectorSettings(
            mavlink_connections=[
                MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udpin:127.0.0.1:14551"),
                MavlinkConnectionConfig(vehicle_id="sitl-1", connection_uri="udpin:127.0.0.1:14552"),
            ]
        )
