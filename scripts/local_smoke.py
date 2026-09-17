"""Exercise the local connector lifecycle without external services."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient

from utm_connector.api import create_app
from utm_connector.config import ConnectorSettings


def _require(response, expected_status: int) -> dict:
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    return response.json()


def main() -> int:
    fixture_path = Path(__file__).parents[1] / "tests" / "fixtures" / "example-mission.json"
    mission = json.loads(fixture_path.read_text(encoding="utf-8"))
    operation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    with TemporaryDirectory(prefix="utm-connector-smoke-") as temporary_directory:
        settings = ConnectorSettings(
            state_db_path=str(Path(temporary_directory) / "state.sqlite3"),
            record_path=None,
            mavlink_connections=[],
        )
        with TestClient(create_app(settings=settings)) as client:
            health = _require(client.get("/v1/health"), 200)
            if health["backend"] != "in-memory":
                raise RuntimeError(f"smoke test expected in-memory backend, got {health['backend']}")

            _require(client.put("/v1/missions/sitl-1", json=mission), 200)
            _require(
                client.post(
                    "/v1/operator-intents?vehicle_id=sitl-1",
                    json={"command": "SUBMIT_OPERATION", "operation_id": operation_id},
                ),
                201,
            )
            started = _require(
                client.post(
                    "/v1/operator-intents?vehicle_id=sitl-1",
                    json={"command": "START_OPERATION", "operation_id": operation_id},
                ),
                201,
            )
            if started["state"]["telemetry_publication"] != "ACTIVE":
                raise RuntimeError("operation did not enter ACTIVE telemetry state")

            telemetry = {
                "vehicle_id": "sitl-1",
                "observed_at": now.isoformat(),
                "latitude": 47.5,
                "longitude": 19.0,
                "altitude": {"meters": 20, "datum": "AGL"},
                "quality": "GOOD",
            }
            status = _require(client.put("/v1/vehicles/sitl-1", json=telemetry), 200)
            if status["vehicle_id"] != "sitl-1":
                raise RuntimeError("telemetry response did not identify the vehicle")

            vehicle_status = _require(client.get("/v1/vehicles/sitl-1/status"), 200)
            if vehicle_status["operations"][0]["state"]["conformance"] != "CONFORMING":
                raise RuntimeError("local conformance assessment did not pass")

            _require(
                client.post(
                    "/v1/operator-intents?vehicle_id=sitl-1",
                    json={"command": "COMPLETE_OPERATION", "operation_id": operation_id},
                ),
                201,
            )

            events = _require(client.get("/v1/events?limit=100"), 200)
            print(
                f"Smoke test passed: operation={operation_id}, "
                f"events={len(events)}, backend={health['backend']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
