"""Verify the lifecycle of an already-running supervised UTM demo.

This is a developer and demo-preparation check, not the normal operator
workflow. It deliberately uses the same connector HTTP contract as the
browser operator console so a passing result covers the live vehicle,
provider, connector, and conformance path together.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx


MISSION_FORMATS = ("canonical", "qgroundcontrol", "mission-planner")


class DemoVerificationError(RuntimeError):
    """Raised when the running demo does not complete its expected lifecycle."""


@dataclass(frozen=True)
class DemoVerificationResult:
    """Small, human-readable summary returned after a successful verification."""

    vehicle_id: str
    operation_id: UUID
    elapsed_s: float
    mission_format: str


def _json(response: httpx.Response, *, expected: int, action: str) -> dict[str, Any]:
    if response.status_code != expected:
        detail = response.text.strip() or "no response body"
        raise DemoVerificationError(
            f"{action} returned HTTP {response.status_code}: {detail}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise DemoVerificationError(f"{action} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DemoVerificationError(f"{action} returned a non-object JSON response")
    return payload


def _state(operation: dict[str, Any], key: str, *, action: str) -> str:
    state = operation.get("state")
    value = state.get(key) if isinstance(state, dict) else None
    if not isinstance(value, str):
        raise DemoVerificationError(f"{action} did not include operation state {key!r}")
    return value


def _mission_upload(
    *,
    vehicle_id: str,
    latitude: float,
    longitude: float,
    altitude_m: float,
    altitude_datum: str,
    valid_from: datetime,
    valid_until: datetime,
    mission_format: str,
) -> tuple[str, dict[str, Any]]:
    """Build the same mission upload a GCS-facing operator workflow uses."""

    if mission_format not in MISSION_FORMATS:
        choices = ", ".join(MISSION_FORMATS)
        raise DemoVerificationError(
            f"unsupported mission format {mission_format!r}; choose one of {choices}"
        )

    route = (
        (latitude, longitude, altitude_m - 2),
        (latitude + 0.0002, longitude + 0.0002, altitude_m + 2),
        (latitude, longitude + 0.0004, altitude_m - 2),
    )
    metadata = {
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "corridor_radius_m": 200,
    }
    if mission_format == "canonical":
        return (
            f"/v1/missions/{vehicle_id}",
            {
                "vehicle_id": vehicle_id,
                **metadata,
                "source": "operator-console-full-stack-verification",
                "waypoints": [
                    {
                        "sequence": sequence,
                        "latitude": point_latitude,
                        "longitude": point_longitude,
                        "altitude": {"meters": point_altitude, "datum": altitude_datum},
                    }
                    for sequence, (point_latitude, point_longitude, point_altitude) in enumerate(route)
                ],
            },
        )

    # MAV_FRAME_GLOBAL(_INT) is the explicit AMSL representation in both
    # QGroundControl Plans and QGC WPL files.  The simulator publishes AMSL
    # telemetry; reject an unexpected datum rather than silently changing it.
    if altitude_datum != "AMSL":
        raise DemoVerificationError(
            f"{mission_format} verification requires AMSL telemetry, got {altitude_datum!r}"
        )
    frame = 5
    if mission_format == "qgroundcontrol":
        items = [
            {
                "type": "SimpleItem",
                "command": command,
                "frame": frame,
                "autoContinue": True,
                "doJumpId": sequence + 1,
                "params": [0, 0, 0, 0, point_latitude, point_longitude, point_altitude],
            }
            for sequence, (command, (point_latitude, point_longitude, point_altitude)) in enumerate(
                zip((22, 16, 21), route)
            )
        ]
        return (
            f"/v1/missions/{vehicle_id}/qgroundcontrol",
            {
                **metadata,
                "plan": {
                    "fileType": "Plan",
                    "groundStation": "QGroundControl",
                    "mission": {"items": items},
                },
            },
        )

    lines = ["QGC WPL 110"]
    for sequence, (command, (point_latitude, point_longitude, point_altitude)) in enumerate(
        zip((22, 16, 21), route)
    ):
        current = 1 if sequence == 0 else 0
        lines.append(
            f"{sequence} {current} {frame} {command} 0 0 0 0 "
            f"{point_latitude} {point_longitude} {point_altitude} 1"
        )
    return (
        f"/v1/missions/{vehicle_id}/mission-planner",
        {**metadata, "text": "\n".join(lines)},
    )


def verify_running_demo(
    base_url: str,
    vehicle_id: str,
    *,
    timeout_s: float = 60.0,
    poll_interval_s: float = 1.0,
    mission_format: str = "canonical",
    client: httpx.Client | None = None,
) -> DemoVerificationResult:
    """Run the operator-console lifecycle against a running connector.

    ``client`` is injectable for unit tests. The default client is closed by
    this function; an injected client remains owned by the caller.
    """

    started_at = time.monotonic()
    owns_client = client is None
    http = client or httpx.Client(timeout=10.0)
    operation_id = uuid4()
    completed = False
    base_url = base_url.rstrip("/")

    try:
        health = _json(
            http.get(f"{base_url}/v1/health"), expected=200, action="health check"
        )
        if health.get("status") not in {"ok", "degraded"}:
            raise DemoVerificationError(
                f"health check reported unexpected status {health.get('status')!r}"
            )

        telemetry_deadline = time.monotonic() + timeout_s
        telemetry: dict[str, Any] | None = None
        while time.monotonic() < telemetry_deadline:
            vehicle_status = _json(
                http.get(f"{base_url}/v1/vehicles/{vehicle_id}/status"),
                expected=200,
                action=f"vehicle {vehicle_id} discovery",
            )
            candidate = vehicle_status.get("latest_telemetry")
            if isinstance(candidate, dict):
                telemetry = candidate
                break
            time.sleep(poll_interval_s)
        if telemetry is None:
            raise DemoVerificationError(
                f"vehicle {vehicle_id} did not publish live telemetry within {timeout_s:.0f}s"
            )
        try:
            latitude = float(telemetry["latitude"])
            longitude = float(telemetry["longitude"])
            altitude = telemetry["altitude"]
            altitude_m = float(altitude["meters"])
            altitude_datum = str(altitude["datum"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DemoVerificationError(
                f"vehicle {vehicle_id} returned incomplete telemetry"
            ) from exc

        now = datetime.now(timezone.utc)
        valid_from = now + timedelta(seconds=15)
        valid_until = now + timedelta(minutes=5)
        mission_path, mission_payload = _mission_upload(
            vehicle_id=vehicle_id,
            latitude=latitude,
            longitude=longitude,
            altitude_m=altitude_m,
            altitude_datum=altitude_datum,
            valid_from=valid_from,
            valid_until=valid_until,
            mission_format=mission_format,
        )
        _json(
            http.put(f"{base_url}{mission_path}", json=mission_payload),
            expected=200,
            action="mission validation",
        )

        submit = _json(
            http.post(
                f"{base_url}/v1/operator-intents",
                params={"vehicle_id": vehicle_id},
                json={
                    "schema_version": "1.0",
                    "command": "SUBMIT_OPERATION",
                    "operation_id": str(operation_id),
                },
            ),
            expected=201,
            action="operation submission",
        )
        if _state(submit, "declaration", action="operation submission") != "ACCEPTED":
            raise DemoVerificationError("operation submission was not accepted")
        if _state(submit, "authorization", action="operation submission") != "AUTHORIZED":
            raise DemoVerificationError("operation submission was not authorized")

        start = _json(
            http.post(
                f"{base_url}/v1/operator-intents",
                params={"vehicle_id": vehicle_id},
                json={
                    "schema_version": "1.0",
                    "command": "START_OPERATION",
                    "operation_id": str(operation_id),
                },
            ),
            expected=201,
            action="operation start",
        )
        if _state(start, "telemetry_publication", action="operation start") != "ACTIVE":
            raise DemoVerificationError("operation did not activate telemetry publication")

        deadline = time.monotonic() + timeout_s
        last_conformance = "UNKNOWN"
        while time.monotonic() < deadline:
            operation = _json(
                http.get(f"{base_url}/v1/operations/{operation_id}"),
                expected=200,
                action="operation status",
            )
            last_conformance = _state(
                operation, "conformance", action="operation status"
            )
            if last_conformance == "CONFORMING":
                break
            time.sleep(poll_interval_s)
        else:
            raise DemoVerificationError(
                f"live telemetry did not reach CONFORMING within {timeout_s:.0f}s "
                f"(last state: {last_conformance})"
            )

        complete = _json(
            http.post(
                f"{base_url}/v1/operator-intents",
                params={"vehicle_id": vehicle_id},
                json={
                    "schema_version": "1.0",
                    "command": "COMPLETE_OPERATION",
                    "operation_id": str(operation_id),
                },
            ),
            expected=201,
            action="operation completion",
        )
        if _state(complete, "declaration", action="operation completion") != "COMPLETED":
            raise DemoVerificationError("operation did not complete")
        if _state(complete, "telemetry_publication", action="operation completion") != "STOPPED":
            raise DemoVerificationError("operation telemetry publication did not stop")
        completed = True

        final_health = _json(
            http.get(f"{base_url}/v1/health"), expected=200, action="final health check"
        )
        if final_health.get("backend_error") is not None:
            raise DemoVerificationError(
                f"final health check reported a backend error: {final_health['backend_error']}"
            )
        metrics = _json(
            http.get(f"{base_url}/v1/metrics"), expected=200, action="metrics check"
        )
        telemetry_metrics = metrics.get("telemetry")
        received_total = telemetry_metrics.get("received_total") if isinstance(telemetry_metrics, dict) else None
        if not isinstance(received_total, (int, float)) or received_total < 1:
            raise DemoVerificationError("metrics check did not report received vehicle telemetry")
        vehicle_metrics = metrics.get("vehicles")
        active_vehicles = vehicle_metrics.get("active") if isinstance(vehicle_metrics, dict) else None
        if not isinstance(active_vehicles, (int, float)) or active_vehicles < 1:
            raise DemoVerificationError("metrics check did not report an active vehicle")
        return DemoVerificationResult(
            vehicle_id=vehicle_id,
            operation_id=operation_id,
            elapsed_s=time.monotonic() - started_at,
            mission_format=mission_format,
        )
    finally:
        if not completed:
            try:
                http.post(
                    f"{base_url}/v1/operator-intents",
                    params={"vehicle_id": vehicle_id},
                    json={
                        "schema_version": "1.0",
                        "command": "CANCEL_OPERATION",
                        "operation_id": str(operation_id),
                    },
                )
            except httpx.HTTPError:
                pass
        if owns_client:
            http.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify an already-running UTM connector demo lifecycle"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--vehicle-id", default="sitl-1")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--mission-format",
        choices=MISSION_FORMATS,
        default="canonical",
        help="mission upload path to exercise (default: canonical)",
    )
    args = parser.parse_args()

    try:
        result = verify_running_demo(
            args.base_url,
            args.vehicle_id,
            timeout_s=args.timeout,
            mission_format=args.mission_format,
        )
    except (DemoVerificationError, httpx.HTTPError) as exc:
        print(f"[fail] full-stack verification: {exc}")
        return 1
    print(
        "[ok] full-stack verification passed: "
        f"vehicle={result.vehicle_id} operation={result.operation_id} "
        f"mission_format={result.mission_format} elapsed={result.elapsed_s:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
