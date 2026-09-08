from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AltitudeDatum(str, Enum):
    AGL = "AGL"
    AMSL = "AMSL"
    WGS84 = "WGS84"
    UNKNOWN = "UNKNOWN"


class DeclarationState(str, Enum):
    NOT_CREATED = "NOT_CREATED"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AuthorizationState(str, Enum):
    UNKNOWN = "UNKNOWN"
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class TelemetryPublicationState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class ConformanceState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONFORMING = "CONFORMING"
    NEAR_BOUNDARY = "NEAR_BOUNDARY"
    NON_CONFORMING = "NON_CONFORMING"
    TELEMETRY_UNRELIABLE = "TELEMETRY_UNRELIABLE"


class TelemetryQuality(str, Enum):
    UNKNOWN = "UNKNOWN"
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INVALID = "INVALID"
    LOST = "LOST"


class VehicleConnectionState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    LOST = "LOST"


class OperationCommand(str, Enum):
    SUBMIT_OPERATION = "SUBMIT_OPERATION"
    START_OPERATION = "START_OPERATION"
    CANCEL_OPERATION = "CANCEL_OPERATION"
    COMPLETE_OPERATION = "COMPLETE_OPERATION"


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


class Altitude(StrictModel):
    meters: float = Field(ge=-1000, le=100000, allow_inf_nan=False)
    datum: AltitudeDatum


class Waypoint(StrictModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    altitude: Altitude
    sequence: int = Field(ge=0)


class Mission(StrictModel):
    mission_id: UUID = Field(default_factory=uuid4)
    vehicle_id: str = Field(min_length=1, max_length=128)
    waypoints: List[Waypoint] = Field(min_length=2)
    corridor_radius_m: float = Field(default=30, gt=0, le=10000, allow_inf_nan=False)
    valid_from: datetime
    valid_until: datetime
    source: str = Field(default="unknown", min_length=1, max_length=64)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _aware_datetime(value)

    @field_validator("valid_until")
    @classmethod
    def validate_time_order(cls, value: datetime, info: Any) -> datetime:
        start = info.data.get("valid_from")
        if start is not None and value <= start:
            raise ValueError("valid_until must be later than valid_from")
        return value

    @field_validator("waypoints")
    @classmethod
    def validate_sequences(cls, value: List[Waypoint]) -> List[Waypoint]:
        sequences = [waypoint.sequence for waypoint in value]
        if sequences != list(range(len(value))):
            raise ValueError("waypoint sequences must be contiguous and start at zero")
        return value

    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"mission_id"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class VehicleTelemetry(StrictModel):
    vehicle_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    altitude: Altitude
    heading_deg: Optional[float] = Field(default=None, ge=0, lt=360, allow_inf_nan=False)
    groundspeed_mps: Optional[float] = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    quality: TelemetryQuality = TelemetryQuality.UNKNOWN

    @field_validator("observed_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _aware_datetime(value)


class VehicleIdentity(StrictModel):
    connector_vehicle_id: str = Field(min_length=1, max_length=128)
    mavlink_system_id: int = Field(ge=1, le=255)
    mavlink_component_ids: List[int] = Field(default_factory=list)
    autopilot_type: Optional[str] = Field(default=None, max_length=64)
    vehicle_type: Optional[str] = Field(default=None, max_length=64)
    firmware_version: Optional[str] = Field(default=None, max_length=128)

    @field_validator("mavlink_component_ids")
    @classmethod
    def validate_component_ids(cls, value: List[int]) -> List[int]:
        if any(component_id < 1 or component_id > 255 for component_id in value):
            raise ValueError("MAVLink component IDs must be between 1 and 255")
        return sorted(set(value))


class VehicleHealth(StrictModel):
    heartbeat_age_s: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    position_age_s: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    gps_fix_type: Optional[int] = Field(default=None, ge=0, le=6)
    satellites_visible: Optional[int] = Field(default=None, ge=0, le=255)
    battery_remaining_pct: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    battery_voltage_v: Optional[float] = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    armed: Optional[bool] = None


class VehicleStateSnapshot(StrictModel):
    identity: VehicleIdentity
    connection_state: VehicleConnectionState
    telemetry: Optional[VehicleTelemetry] = None
    quality: TelemetryQuality = TelemetryQuality.UNKNOWN
    health: VehicleHealth = Field(default_factory=VehicleHealth)
    mission_current: Optional[int] = Field(default=None, ge=0)
    mission_count: Optional[int] = Field(default=None, ge=0)
    diagnostics: List[str] = Field(default_factory=list)


class MissionSnapshot(StrictModel):
    mission: Mission
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mission_hash: str

    @field_validator("received_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _aware_datetime(value)


class OperationalVolume(StrictModel):
    geometry_type: Literal["Polygon"] = "Polygon"
    coordinates: List[List[List[float]]] = Field(min_length=1)
    lower_altitude: Altitude
    upper_altitude: Altitude

    @field_validator("coordinates")
    @classmethod
    def validate_polygon_coordinates(cls, value: List[List[List[float]]]) -> List[List[List[float]]]:
        if not value or len(value[0]) < 4:
            raise ValueError("polygon outer ring must contain at least four positions")
        for ring in value:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("polygon rings must be closed and contain at least four positions")
            for position in ring:
                if len(position) != 2:
                    raise ValueError("polygon positions must be [longitude, latitude]")
                longitude, latitude = position
                if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                    raise ValueError("polygon coordinates are outside WGS84 bounds")
        return value

    @model_validator(mode="after")
    def validate_altitude_order(self) -> "OperationalVolume":
        if self.lower_altitude.datum != self.upper_altitude.datum:
            raise ValueError("operational volume altitude datums must match")
        if self.lower_altitude.meters > self.upper_altitude.meters:
            raise ValueError("lower_altitude must not exceed upper_altitude")
        return self


class CorridorGeometry(StrictModel):
    mission_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    projected_crs: str = Field(min_length=1, max_length=128)
    corridor_radius_m: float = Field(gt=0, le=10000, allow_inf_nan=False)
    volume: OperationalVolume


class OperationState(StrictModel):
    declaration: DeclarationState = DeclarationState.DRAFT
    authorization: AuthorizationState = AuthorizationState.UNKNOWN
    telemetry_publication: TelemetryPublicationState = TelemetryPublicationState.NOT_STARTED
    conformance: ConformanceState = ConformanceState.UNKNOWN


class Operation(StrictModel):
    operation_id: UUID = Field(default_factory=uuid4)
    vehicle_id: str = Field(min_length=1, max_length=128)
    mission_id: UUID
    mission_hash: str
    state: OperationState = Field(default_factory=OperationState)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _aware_datetime(value)


class Envelope(StrictModel):
    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    correlation_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _aware_datetime(value)


class OperationIntent(Envelope):
    operation_id: UUID
    command: OperationCommand


class HealthResponse(StrictModel):
    status: str = "ok"
    backend: str = "in-memory"
    active_vehicles: int = Field(ge=0)
    active_operations: int = Field(ge=0)


class Event(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str
    severity: str = "INFO"
    correlation_id: Optional[UUID] = None
    vehicle_id: Optional[str] = None
    operation_id: Optional[UUID] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _aware_datetime(value)
