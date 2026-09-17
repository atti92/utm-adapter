"""Environment-backed connector configuration."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MavlinkConnectionConfig(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=128)
    connection_uri: str = Field(min_length=1, max_length=256)


class ConnectorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UTM_CONNECTOR_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "info"
    state_db_path: str = "connector-state.sqlite3"
    event_history_limit: int = Field(default=1000, ge=1, le=100_000)
    record_path: str | None = None
    backend: str = Field(default="in-memory", pattern=r"^(in-memory|flight-blender)$")
    flight_blender_base_url: str = "http://127.0.0.1:8989"
    flight_blender_bearer_token: str | None = None
    flight_blender_timeout_s: float = Field(default=10.0, gt=0, le=120)
    flight_blender_max_retries: int = Field(default=3, ge=0, le=10)
    flight_blender_retry_backoff_s: float = Field(default=0.25, ge=0, le=60)
    flight_blender_type_of_operation: int = Field(default=1, ge=1, le=3)
    flight_blender_submitted_by: str = "utm-operations-connector"
    flight_blender_originating_party: str = "utm-operations-connector"
    mavlink_connections: List[MavlinkConnectionConfig] = Field(default_factory=list)
    mavlink_poll_interval_s: float = Field(default=0.2, gt=0, le=10)
