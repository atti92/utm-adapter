"""Small provider-neutral HTTP client for thin GCS adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx

from .domain import OperationCommand


class ConnectorClientError(RuntimeError):
    """A connector request failed before a GCS action could complete."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConnectorClient:
    """Call the local connector API from a thin GCS integration.

    The client returns JSON dictionaries intentionally: a host application can
    map them into its own UI models without importing provider-specific types.
    It never opens or controls a vehicle connection; MAVLink remains owned by
    the connector boundary.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=10.0)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "ConnectorClient":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def vehicles(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/vehicles")

    def vehicle_status(self, vehicle_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/vehicles/{self._path_value(vehicle_id)}/status")

    def mission(self, vehicle_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/missions/{self._path_value(vehicle_id)}")

    def upload_qgroundcontrol_plan(
        self,
        vehicle_id: str,
        plan: Mapping[str, Any],
        *,
        valid_from: datetime,
        valid_until: datetime,
        corridor_radius_m: float = 30,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/v1/missions/{self._path_value(vehicle_id)}/qgroundcontrol",
            json={
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "corridor_radius_m": corridor_radius_m,
                "plan": dict(plan),
            },
        )

    def upload_mission_planner_waypoints(
        self,
        vehicle_id: str,
        text: str,
        *,
        valid_from: datetime,
        valid_until: datetime,
        corridor_radius_m: float = 30,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/v1/missions/{self._path_value(vehicle_id)}/mission-planner",
            json={
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "corridor_radius_m": corridor_radius_m,
                "text": text,
            },
        )

    def operation_intent(
        self,
        vehicle_id: str,
        command: OperationCommand | str,
        *,
        operation_id: Optional[UUID | str] = None,
    ) -> dict[str, Any]:
        resolved_operation_id = str(operation_id or uuid4())
        resolved_command = command.value if isinstance(command, OperationCommand) else command
        return self._request(
            "POST",
            f"/v1/operator-intents?vehicle_id={quote(vehicle_id, safe='')}",
            json={
                "schema_version": "1.0",
                "command": resolved_command,
                "operation_id": resolved_operation_id,
            },
        )

    def refresh_operation(self, operation_id: UUID | str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/operations/{self._path_value(str(operation_id))}/refresh",
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise ConnectorClientError(f"connector request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorClientError(
                f"connector returned invalid JSON ({response.status_code})",
                status_code=response.status_code,
            ) from exc
        if not response.is_success:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            raise ConnectorClientError(str(detail), status_code=response.status_code)
        return payload

    @staticmethod
    def _path_value(value: str) -> str:
        return quote(value, safe="")
