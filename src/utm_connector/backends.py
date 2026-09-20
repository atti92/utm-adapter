from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from time import monotonic, sleep
from typing import Dict, List, Optional

import httpx

from .auth import OAuthClientCredentials, OAuthError
from .domain import (
    AltitudeDatum,
    AuthorizationState,
    DeclarationState,
    Mission,
    Operation,
    OperationCommand,
    VehicleTelemetry,
)
from .geometry import GeometryError, build_corridor
from .observability import RuntimeMetrics
from .recording import JsonlRecorder


class UTMBackend(ABC):
    name = "backend"
    required_altitude_datum: Optional[AltitudeDatum] = None

    def mission_window_constraints(self) -> dict:
        """Return provider rules the operator console can validate locally."""

        return {
            "requires_future_start": False,
            "max_future_seconds": None,
        }

    @abstractmethod
    def submit_operation(self, operation: Operation, mission: Mission) -> Operation:
        """Submit an operation and return the provider-normalized result."""

    @abstractmethod
    def publish_telemetry(
        self, telemetry: VehicleTelemetry, operation: Optional[Operation] = None
    ) -> None:
        """Publish one canonical telemetry observation for an operation."""

    @abstractmethod
    def update_operation(self, operation: Operation, command: OperationCommand) -> Operation:
        """Apply an operator intent to a provider operation."""

    @abstractmethod
    def fetch_operation(self, operation: Operation) -> dict:
        """Fetch provider-owned state for an operation."""


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

    def publish_telemetry(
        self, telemetry: VehicleTelemetry, operation: Optional[Operation] = None
    ) -> None:
        self.telemetry.append(telemetry)

    def update_operation(self, operation: Operation, command: OperationCommand) -> Operation:
        return operation

    def fetch_operation(self, operation: Operation) -> dict:
        provider_state = {
            DeclarationState.SUBMITTED: 0,
            DeclarationState.ACCEPTED: 1,
            DeclarationState.COMPLETED: 5,
            DeclarationState.REJECTED: 8,
            DeclarationState.CANCELLED: 7,
        }.get(operation.state.declaration, 0)
        return {
            "id": str(operation.operation_id),
            "state": provider_state,
            "is_approved": operation.state.authorization == AuthorizationState.AUTHORIZED,
        }


class BackendError(RuntimeError):
    """Raised when a provider cannot accept or publish connector data."""


class FlightBlenderBackend(UTMBackend):
    """HTTP adapter for the Flight Blender flight declaration and RID APIs."""

    name = "flight-blender"
    required_altitude_datum = AltitudeDatum.WGS84
    max_declaration_horizon_s = 2 * 24 * 60 * 60

    def mission_window_constraints(self) -> dict:
        # Flight Blender validates both declaration timestamps against its
        # current clock. Exposing the rule lets a browser console provide an
        # actionable message before a declaration reaches the provider.
        return {
            "requires_future_start": True,
            "max_future_seconds": self.max_declaration_horizon_s,
        }

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: Optional[str] = None,
        oauth_token_url: Optional[str] = None,
        oauth_client_id: Optional[str] = None,
        oauth_client_secret: Optional[str] = None,
        oauth_scope: Optional[str] = None,
        timeout_s: float = 10.0,
        max_retries: int = 3,
        retry_backoff_s: float = 0.25,
        type_of_operation: int = 1,
        submitted_by: str = "utm-operations-connector",
        originating_party: str = "utm-operations-connector",
        client: Optional[httpx.Client] = None,
        recorder: Optional[JsonlRecorder] = None,
        metrics: Optional[RuntimeMetrics] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.type_of_operation = type_of_operation
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s
        self.submitted_by = submitted_by
        self.originating_party = originating_party
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_s)
        self._closed = False
        self._provider_operation_ids: Dict[str, str] = {}
        # Kept only for callers of the historical telemetry-only method. A
        # vehicle can have multiple operations, so connector service calls
        # always resolve through the operation-specific map above.
        self._legacy_provider_operation_ids: Dict[str, str] = {}
        self.recorder = recorder
        self.metrics = metrics or RuntimeMetrics()
        oauth_values = (oauth_token_url, oauth_client_id, oauth_client_secret)
        if any(oauth_values) and bearer_token:
            raise ValueError("configure either bearer_token or OAuth client credentials, not both")
        if any(oauth_values) and not all(oauth_values):
            raise ValueError("OAuth client credentials require token URL, client ID, and client secret")
        self._oauth = (
            OAuthClientCredentials(
                oauth_token_url,
                oauth_client_id,
                oauth_client_secret,
                scope=oauth_scope,
                client=self.client,
            )
            if all(oauth_values)
            else None
        )

    def submit_operation(self, operation: Operation, mission: Mission) -> Operation:
        self._validate_declaration_window(mission)
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
        self._provider_operation_ids[str(operation.operation_id)] = provider_operation_id
        self._legacy_provider_operation_ids[operation.vehicle_id] = provider_operation_id
        updated = operation.model_copy(update={"provider_operation_id": provider_operation_id})
        provider_state = response.get("state")
        approved = response.get("is_approved")
        if isinstance(provider_state, int):
            updated = updated.model_copy(
                update={
                    "state": updated.state.model_copy(
                        update={"declaration": _declaration_state(provider_state)}
                    )
                }
            )
        if isinstance(approved, bool) or isinstance(approved, int):
            authorization = (
                AuthorizationState.AUTHORIZED if bool(approved) else AuthorizationState.PENDING
            )
            updated = updated.model_copy(
                update={"state": updated.state.model_copy(update={"authorization": authorization})}
            )
        return updated

    def _validate_declaration_window(self, mission: Mission) -> None:
        now = datetime.now(timezone.utc)
        if mission.valid_from <= now:
            raise BackendError(
                "Flight Blender declarations must start in the future; "
                "move the operation validity window forward"
            )
        latest_allowed = now.timestamp() + self.max_declaration_horizon_s
        if mission.valid_from.timestamp() > latest_allowed or mission.valid_until.timestamp() > latest_allowed:
            raise BackendError(
                "Flight Blender declarations must start and end within two days of the current time"
            )

    def publish_telemetry(
        self, telemetry: VehicleTelemetry, operation: Optional[Operation] = None
    ) -> None:
        if telemetry.altitude.datum != self.required_altitude_datum:
            raise BackendError(
                "Flight Blender telemetry requires WGS84 altitude; "
                f"received {telemetry.altitude.datum.value}"
            )
        if operation is not None and operation.vehicle_id != telemetry.vehicle_id:
            raise BackendError("telemetry vehicle_id does not match the operation vehicle_id")
        operation_id = None
        if operation is not None:
            operation_id = operation.provider_operation_id or self._provider_operation_ids.get(
                str(operation.operation_id)
            )
        else:
            operation_id = self._legacy_provider_operation_ids.get(telemetry.vehicle_id)
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

    def update_operation(self, operation: Operation, command: OperationCommand) -> Operation:
        provider_operation_id = operation.provider_operation_id
        if provider_operation_id is None:
            raise BackendError("cannot update a Flight Blender operation without a provider declaration id")
        provider_state = {
            OperationCommand.START_OPERATION: 2,
            OperationCommand.CANCEL_OPERATION: 7,
            OperationCommand.COMPLETE_OPERATION: 5,
        }.get(command)
        if provider_state is None:
            raise BackendError(f"unsupported provider operation command: {command.value}")
        self._request(
            "PUT",
            f"/flight_declaration_ops/flight_declaration_state/{provider_operation_id}",
            json={"state": provider_state},
        )
        return operation

    def fetch_operation(self, operation: Operation) -> dict:
        """Fetch the provider declaration for diagnostics and state reconciliation."""
        provider_operation_id = operation.provider_operation_id
        if provider_operation_id is None:
            raise BackendError("cannot fetch a Flight Blender operation without a provider declaration id")
        return self._request(
            "GET",
            f"/flight_declaration_ops/flight_declaration/{provider_operation_id}",
            json=None,
        )

    def register_operation(self, operation: Operation) -> None:
        """Restore a provider operation mapping loaded from persistent state."""
        if operation.provider_operation_id:
            self._provider_operation_ids[str(operation.operation_id)] = operation.provider_operation_id
            self._legacy_provider_operation_ids[operation.vehicle_id] = operation.provider_operation_id

    def close(self) -> None:
        if not self._closed and self._owns_client:
            self.client.close()
        self._closed = True

    @property
    def authentication_mode(self) -> str:
        if self._oauth is not None:
            return "oauth-client-credentials"
        if self.bearer_token:
            return "bearer-token"
        return "none"

    def _request(self, method: str, path: str, *, json: Optional[dict]) -> dict:
        last_error: Exception | None = None
        auth_refresh_used = False
        total_attempts = self.max_retries + 1 + (1 if self._oauth is not None else 0)
        for attempt in range(total_attempts):
            started = monotonic()
            try:
                headers = {"Accept": "application/json"}
                if self.bearer_token:
                    headers["Authorization"] = f"Bearer {self.bearer_token}"
                elif self._oauth is not None:
                    headers["Authorization"] = f"Bearer {self._oauth.get_token(force_refresh=auth_refresh_used)}"
                if self.recorder is not None:
                    self.recorder.record(
                        "backend_request",
                        {"method": method, "path": path, "headers": _safe_headers(headers), "json": json},
                    )
                response = self.client.request(method, f"{self.base_url}{path}", json=json, headers=headers)
                if self.recorder is not None:
                    self.recorder.record(
                        "backend_response",
                        {"method": method, "path": path, "status_code": response.status_code, "body": _response_body(response)},
                    )
                if response.status_code == 204:
                    self.metrics.record_backend_request(monotonic() - started, success=True)
                    return {}
                if response.status_code == 401 and self._oauth is not None and not auth_refresh_used:
                    self._oauth.invalidate()
                    auth_refresh_used = True
                    continue
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise BackendError(f"Flight Blender request {method} {path} returned a non-object response")
                self.metrics.record_backend_request(monotonic() - started, success=True)
                return body
            except BackendError:
                self.metrics.record_backend_request(monotonic() - started, success=False)
                raise
            except OAuthError as exc:
                self.metrics.record_backend_request(monotonic() - started, success=False)
                raise BackendError(f"Flight Blender authentication failed: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                self.metrics.record_backend_request(monotonic() - started, success=False)
                if exc.response.status_code != 429 and exc.response.status_code < 500:
                    detail = _response_body(exc.response)
                    raise BackendError(
                        f"Flight Blender request {method} {path} failed with HTTP "
                        f"{exc.response.status_code}: {detail}"
                    ) from exc
                last_error = exc
                if attempt >= self.max_retries:
                    break
                sleep(self.retry_backoff_s * (2**attempt))
            except httpx.RequestError as exc:
                self.metrics.record_backend_request(monotonic() - started, success=False)
                last_error = exc
                if attempt >= self.max_retries:
                    break
                sleep(self.retry_backoff_s * (2**attempt))
            except ValueError as exc:
                self.metrics.record_backend_request(monotonic() - started, success=False)
                raise BackendError(f"Flight Blender request {method} {path} returned invalid JSON: {exc}") from exc
        raise BackendError(f"Flight Blender request {method} {path} failed after retries: {last_error}") from last_error


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _declaration_state(provider_state: int) -> DeclarationState:
    if provider_state == 8:
        return DeclarationState.REJECTED
    if provider_state in (6, 7):
        return DeclarationState.CANCELLED
    if provider_state == 5:
        return DeclarationState.COMPLETED
    if provider_state in (1, 2, 3, 4):
        return DeclarationState.ACCEPTED
    return DeclarationState.SUBMITTED


def _current_state(telemetry: VehicleTelemetry) -> dict:
    return {
        # Flight Blender defaults the omitted format to RFC3339. Keeping the
        # nested value string-only also avoids its local serializer's handling
        # of nested enum instances.
        "timestamp": {"value": _rfc3339(telemetry.observed_at)},
        "timestamp_accuracy": 0.0,
        "position": {
            "lat": telemetry.latitude,
            "lng": telemetry.longitude,
            "accuracy_h": "HAUnknown",
            "accuracy_v": "VAUnknown",
            "height": None,
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


def _safe_headers(headers: Dict[str, str]) -> Dict[str, str]:
    return {key: "<redacted>" if key.lower() == "authorization" else value for key, value in headers.items()}


def _response_body(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text[:2000]
