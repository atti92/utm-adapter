from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from .domain import AltitudeDatum, Mission, Operation, VehicleTelemetry
from .geometry import GeometryError, build_corridor


class UTMBackend(ABC):
    name = "backend"

    @abstractmethod
    def submit_operation(self, operation: Operation, mission: Mission) -> Operation:
        """Submit an operation and return the provider-normalized result."""

    @abstractmethod
    def publish_telemetry(self, telemetry: VehicleTelemetry) -> None:
        """Publish one canonical telemetry observation."""


class InMemoryBackend(UTMBackend):
    """Deterministic backend used by the local environment and tests."""

    name = "in-memory"

    def __init__(self) -> None:
        self.operations: Dict[str, Operation] = {}
        self.missions: Dict[str, Mission] = {}
        self.telemetry: List[VehicleTelemetry] = []

    def submit_operation(self, operation: Operation, mission: Mission) -> Operation:
        self.operations[str(operation.operation_id)] = operation
        self.missions[str(operation.operation_id)] = mission
        return operation

    def publish_telemetry(self, telemetry: VehicleTelemetry) -> None:
        self.telemetry.append(telemetry)


class BackendError(RuntimeError):
    """Raised when a provider cannot accept or publish connector data."""


class FlightBlenderBackend(UTMBackend):
    """HTTP adapter for the Flight Blender flight declaration and RID APIs."""

    name = "flight-blender"

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: Optional[str] = None,
        timeout_s: float = 10.0,
        type_of_operation: int = 1,
        submitted_by: str = "utm-operations-connector",
        originating_party: str = "utm-operations-connector",
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.type_of_operation = type_of_operation
        self.submitted_by = submitted_by
        self.originating_party = originating_party
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_s)
        self._provider_operation_ids: Dict[str, str] = {}

    def submit_operation(self, operation: Operation, mission: Mission) -> Operation:
        try:
            corridor = build_corridor(mission)
        except GeometryError as exc:
            raise BackendError(f"cannot create Flight Blender volume: {exc}") from exc
        if corridor.volume.lower_altitude.datum != AltitudeDatum.WGS84:
            raise BackendError(
                "Flight Blender declarations require WGS84 altitude datums; "
                f"received {corridor.volume.lower_altitude.datum.value}"
            )

        payload = {
            "originating_party": self.originating_party,
            "submitted_by": self.submitted_by,
            "start_datetime": _rfc3339(mission.valid_from),
            "end_datetime": _rfc3339(mission.valid_until),
            "flight_declaration_geo_json": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": corridor.volume.geometry_type,
                            "coordinates": corridor.volume.coordinates,
                        },
                        "properties": {
                            "min_altitude": {
                                "meters": corridor.volume.lower_altitude.meters,
                                "datum": "WGS84",
                            },
                            "max_altitude": {
                                "meters": corridor.volume.upper_altitude.meters,
                                "datum": "WGS84",
                            },
                            "connector_operation_id": str(operation.operation_id),
                        },
                    }
                ],
            },
            "type_of_operation": self.type_of_operation,
            "aircraft_id": operation.vehicle_id,
        }
        response = self._request("POST", "/flight_declaration_ops/set_flight_declaration", json=payload)
        provider_operation_id = response.get("id")
        if not isinstance(provider_operation_id, str) or not provider_operation_id:
            raise BackendError("Flight Blender response did not include a declaration id")
        self._provider_operation_ids[operation.vehicle_id] = provider_operation_id
        return operation.model_copy(update={"provider_operation_id": provider_operation_id})

    def publish_telemetry(self, telemetry: VehicleTelemetry) -> None:
        operation_id = self._provider_operation_ids.get(telemetry.vehicle_id)
        if operation_id is None:
            raise BackendError(
                f"cannot publish telemetry for {telemetry.vehicle_id}: no submitted operation is known"
            )
        self._request(
            "PUT",
            "/flight_stream/set_telemetry",
            json={
                "observations": [
                    {
                        "current_states": [_current_state(telemetry)],
                        "flight_details": {
                            "id": operation_id,
                            "operator_id": self.submitted_by,
                            "operation_description": "MAVLink vehicle telemetry",
                            "uas_id": {"serial_number": telemetry.vehicle_id},
                        },
                    }
                ]
            },
        )

    def register_operation(self, operation: Operation) -> None:
        """Restore a provider operation mapping loaded from persistent state."""
        if operation.provider_operation_id:
            self._provider_operation_ids[operation.vehicle_id] = operation.provider_operation_id

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _request(self, method: str, path: str, *, json: dict) -> dict:
        headers = {"Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        try:
            response = self.client.request(method, f"{self.base_url}{path}", json=json, headers=headers)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BackendError(f"Flight Blender request {method} {path} failed: {exc}") from exc
        if not isinstance(body, dict):
            raise BackendError(f"Flight Blender request {method} {path} returned a non-object response")
        return body


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _current_state(telemetry: VehicleTelemetry) -> dict:
    reference = "GroundLevel" if telemetry.altitude.datum == AltitudeDatum.AGL else "TakeoffLocation"
    return {
        "timestamp": {"value": _rfc3339(telemetry.observed_at), "format": "RFC3339"},
        "timestamp_accuracy": 0.0,
        "position": {
            "lat": telemetry.latitude,
            "lng": telemetry.longitude,
            "accuracy_h": "HAUnknown",
            "accuracy_v": "VAUnknown",
            "height": {"reference": reference, "distance": telemetry.altitude.meters},
            "alt": telemetry.altitude.meters,
            "pressure_altitude": -1000,
            "extrapolated": False,
        },
        "speed_accuracy": "SAUnknown",
        "operational_status": "Airborne",
        "speed": telemetry.groundspeed_mps if telemetry.groundspeed_mps is not None else 255,
        "track": telemetry.heading_deg if telemetry.heading_deg is not None else 361,
        "vertical_speed": 63,
    }
