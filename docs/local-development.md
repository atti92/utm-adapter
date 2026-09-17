# Local development environment

The repository contains a local connector based on the implementation plan. It runs a loopback-only FastAPI service with an in-memory backend by default, and includes read-only MAVLink normalization plus QGroundControl mission and corridor tests, so product behavior can be exercised without credentials or a deployed UTM provider. It can also submit declarations and RID telemetry to a local or remote Flight Blender instance.

## Requirements

- Python 3.10 through 3.13
- [uv](https://docs.astral.sh/uv/)

Python 3.10 is retained temporarily for compatibility, but is scheduled for removal after its upstream security-support window closes in October 2026. New development and CI should prefer Python 3.11–3.13. The CI matrix covers Linux, macOS, and Windows.

## Fastest setup check

```sh
uv sync
uv run python scripts/doctor.py
uv run python scripts/local_smoke.py
```

The doctor validates configuration and writable local state. The smoke test
uses a temporary SQLite database and an in-memory UTM backend, then exercises
the complete local lifecycle without starting a simulator or contacting a
provider. It is the quickest way to tell whether the installation is usable.

## Start the local connector

```sh
uv run utm-connector
```

The command uses an application factory, so importing connector code for tests
or diagnostics does not open the persistent SQLite database. The equivalent
direct Uvicorn command is:

```sh
uv run uvicorn 'utm_connector.api:create_app' --factory
```

Convenience targets are also available: `make setup`, `make doctor`, `make smoke`,
`make test`, and `make run`. They delegate to `uv run`, so they do not depend on
the Unix-specific `.venv/bin` layout.

The service listens on `http://127.0.0.1:8000`. OpenAPI is available at `/docs`,
and the health endpoint is `/v1/health`.

For GCS integration, start with the discovery endpoints:

```sh
curl http://127.0.0.1:8000/v1/capabilities
curl http://127.0.0.1:8000/v1/health
curl http://127.0.0.1:8000/v1/vehicles
```

`/v1/capabilities` describes supported mission formats, operator commands, and
the read-only MAVLink behavior. `/v1/vehicles` lists discovered vehicles,
telemetry freshness, active operation count, and the last session error when a
simulator or router cannot be reached. A `degraded` health status means at least
one configured MAVLink session currently has an error.

For a clean disposable run, use this in `.env`:

```dotenv
UTM_CONNECTOR_STATE_DB_PATH=:memory:
UTM_CONNECTOR_MAVLINK_CONNECTIONS=[]
```

For a normal local run, keep the default SQLite path so operations and recent
telemetry survive a restart. If an old test operation makes the state confusing,
stop the connector and switch temporarily to `:memory:` rather than deleting
state while diagnosing the workflow.

## Connect a simulator over MAVLink

The connector can run one or more read-only MAVLink sessions in the background. Copy `.env.example` to `.env` and set the connection list to the URI exposed by your simulator or MAVLink router:

```dotenv
UTM_CONNECTOR_MAVLINK_CONNECTIONS=[{"vehicle_id":"sitl-1","connection_uri":"udpin:127.0.0.1:14551"}]
UTM_CONNECTOR_MAVLINK_POLL_INTERVAL_S=0.2
```

Then start the connector with `uv run utm-connector` (or `make run`) and inspect live state at:

```sh
curl http://127.0.0.1:8000/v1/vehicles/sitl-1/status
```

Use a MAVLink router or separate simulator output port if QGroundControl or Mission Planner is also listening on the same UDP port. This path only reads MAVLink telemetry; it does not send vehicle commands.

### ArduPilot SITL and QGroundControl

The prepared macOS setup uses two simulator outputs so the GCS and connector can observe the same vehicle independently:

```text
ArduPilot SITL --UDP 14550--> QGroundControl
                 --UDP 14551--> UTM connector
```

From the ArduPilot checkout, start the prepared ArduCopter binary with (replace the placeholder path):

```sh
ARDUPILOT_ROOT=/path/to/ardupilot
cd "$ARDUPILOT_ROOT"
PATH="$ARDUPILOT_ROOT/.venv/bin:$PATH" \
  ./Tools/autotest/sim_vehicle.py \
  -v ArduCopter -N \
  --out=udpout:127.0.0.1:14550 \
  --out=udpout:127.0.0.1:14551
```

Then start one GCS and the connector in separate terminals. Launch
QGroundControl or Mission Planner from the application menu; on macOS,
QGroundControl can also be started with:

```sh
open -a QGroundControl
```

From the connector checkout, use `uv run utm-connector` (or `make run` on
systems with `make`).

QGroundControl should show the SITL vehicle automatically. The connector state can be checked with:

```sh
curl http://127.0.0.1:8000/v1/vehicles/sitl-1/status
```

The default local UTM is the connector's in-memory backend, so no external UTM service or account is required for the basic test loop. To use Flight Blender, set these values in `.env`:

```dotenv
UTM_CONNECTOR_BACKEND=flight-blender
UTM_CONNECTOR_FLIGHT_BLENDER_BASE_URL=http://127.0.0.1:8989
UTM_CONNECTOR_FLIGHT_BLENDER_BEARER_TOKEN=
UTM_CONNECTOR_FLIGHT_BLENDER_MAX_RETRIES=3
UTM_CONNECTOR_FLIGHT_BLENDER_RETRY_BACKOFF_S=0.25
UTM_CONNECTOR_RECORD_PATH=connector-events.jsonl
```

The adapter calls Flight Blender's `set_flight_declaration` endpoint with the generated WGS84 corridor and stores the provider declaration ID in the local operation record. It calls `set_telemetry` with the provider ID for subsequent telemetry. A mission whose altitude datum is AGL or AMSL is intentionally rejected for declaration submission because the connector does not have enough information to convert it to WGS84 safely; use WGS84 mission altitudes for this integration path.

When `UTM_CONNECTOR_RECORD_PATH` is set, connector events and backend request/response envelopes are appended as JSONL. Authorization headers are redacted. Replay the file in a diagnostic tool with `JsonlReplay`:

```python
from utm_connector.recording import JsonlReplay

JsonlReplay("connector-events.jsonl").replay(lambda kind, payload: print(kind, payload))
```

## Run tests

```sh
uv run pytest
```

## Exercise the API

Upload a mission, submit it, start it, and publish telemetry:

```sh
curl -X PUT http://127.0.0.1:8000/v1/missions/sitl-1 \
  -H 'content-type: application/json' \
  -d @tests/fixtures/example-mission.json

curl -X POST 'http://127.0.0.1:8000/v1/operator-intents?vehicle_id=sitl-1' \
  -H 'content-type: application/json' \
  -d '{"schema_version":"1.0","command":"SUBMIT_OPERATION","operation_id":"00000000-0000-0000-0000-000000000001"}'
```

The local backend accepts the declaration and marks it authorized to make the happy-path lifecycle testable. This is a development behavior. Flight Blender authorization and state transitions remain provider-owned; inspect the provider response and Flight Blender UI/API when using the real adapter.

### Check onboard mission drift

The connector can compare the submitted canonical mission with a mission snapshot
read from a GCS or simulator. This local endpoint stands in for the future
MAVLink mission reader:

```sh
curl -X PUT http://127.0.0.1:8000/v1/vehicles/sitl-1/onboard-mission \
  -H 'content-type: application/json' \
  -d @tests/fixtures/example-mission.json
```

The response contains `classification`, both canonical hashes, and the changed
field paths. An unchanged mission returns `NO_CHANGE`; route, altitude, or time
changes return the corresponding classification. A change spanning multiple
operational categories is conservatively reported as `UNKNOWN_CHANGE`. The
latest report is also included in `/v1/vehicles/sitl-1/status`.

## Exercise the mission adapters

QGroundControl `.plan` files can be passed to `parse_qgroundcontrol_plan` and become the same canonical `Mission` model used by the API. `build_corridor` then projects the WGS84 route to a local metre-based CRS before buffering it; altitude datums are required and are never inferred. The unit tests in `tests/test_missions.py` and `tests/test_geometry.py` provide offline examples of both boundaries.

For a zero-fork QGroundControl integration, send the plan with explicit UTM
validity metadata:

```sh
curl -X PUT http://127.0.0.1:8000/v1/missions/sitl-1/qgroundcontrol \
  -H 'content-type: application/json' \
  -d '{"valid_from":"2030-01-01T12:00:00Z","valid_until":"2030-01-01T12:30:00Z","corridor_radius_m":30,"plan":{"fileType":"Plan","mission":{"items":[]}}}'
```

Replace the empty `items` list with the exported QGC `SimpleItem` entries. The
endpoint rejects unsupported mission items and requires the caller to provide
the validity window because a `.plan` file does not define the UTM declaration
window.
