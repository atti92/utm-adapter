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


def test_provider_oauth_credentials_must_be_complete_and_exclusive() -> None:
    with pytest.raises(ValidationError, match="requires: flight_blender_client_secret"):
        ConnectorSettings(
            flight_blender_token_url="https://auth.example.test/token",
            flight_blender_client_id="connector",
        )

    with pytest.raises(ValidationError, match="either FLIGHT_BLENDER_BEARER_TOKEN"):
        ConnectorSettings(
            flight_blender_bearer_token="local-token",
            flight_blender_token_url="https://auth.example.test/token",
            flight_blender_client_id="connector",
            flight_blender_client_secret="secret",
        )
