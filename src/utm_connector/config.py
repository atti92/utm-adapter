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
    mavlink_connections: List[MavlinkConnectionConfig] = Field(default_factory=list)
    mavlink_poll_interval_s: float = Field(default=0.2, gt=0, le=10)
