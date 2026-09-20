# Local development environment

The repository contains a local connector based on the implementation plan. It runs a loopback-only FastAPI service with an in-memory backend by default, includes a browser-based operator console, and provides non-commanding MAVLink normalization plus QGroundControl mission and corridor tests. Product behavior can therefore be exercised without credentials or a deployed UTM provider. It can also submit declarations and RID telemetry to a local or remote Flight Blender instance.

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

The doctor validates configuration, writable local state, whether the API
port already has a listener, and—when Flight Blender is selected—whether its
`/ping` endpoint is reachable. If a bearer token is configured and the
provider is reachable, it also checks a protected read endpoint so malformed
or under-scoped local tokens fail before a mission is submitted. Provider
reachability remains informational when the dependency is not started. The smoke test
uses a temporary SQLite database and an in-memory UTM backend, then exercises
the complete local lifecycle without starting a simulator or contacting a
provider. It is the quickest way to tell whether the installation is usable.

## Start the local connector

```sh
uv run utm-connector
```

For a one-command local demo that opens the operator console automatically:

```sh
uv run utm-connector --demo --open-browser
# or, on systems with make:
make demo
```

The `--demo` flag explicitly selects the in-memory backend, disables configured
MAVLink inputs, and publishes a moving `demo-sitl` vehicle. It overrides local
`.env` backend and state settings for that process, so every presentation starts
clean and does not modify the normal SQLite history. The browser launch uses the
platform's default browser and does not
change the connector's loopback-only default or send any vehicle-control
commands.

For a standalone UI demonstration without a simulator, use the command above.
Demo mode is opt-in and is not intended for live vehicle operation.

### One-command full-stack demo

When the Flight Blender and ArduPilot checkouts are available, the supervised
launcher provides the shortest path to a realistic GCS-facing demonstration:

```sh
uv run python scripts/openutm_demo.py --check
uv run python scripts/openutm_demo.py
```

It starts the local Flight Blender Compose stack, the connector configured for
Flight Blender, and ArduPilot SITL with one telemetry output for a GCS and one
for the connector. It opens the browser console and launches QGroundControl if
it is installed. The browser console is where the UTM operator workflow is
performed: choose the detected vehicle, select `Sample route` or open a
QGroundControl `.plan`/Mission Planner `.waypoints` export, then validate, submit,
and start the operation. The GCS remains the vehicle-control application.

If the default simulator endpoints are already used, choose different ports
without editing configuration files, for example:

```sh
uv run python scripts/openutm_demo.py --gcs-udp-port 14560 --connector-udp-port 14561
```

Set `FLIGHT_BLENDER_ROOT` and `ARDUPILOT_ROOT` when the checkouts are not in
the sibling directories next to this repository. The same Python launcher can
be run from PowerShell; use `--gcs mission-planner` on Windows when Mission
Planner is installed. `Ctrl+C` cleans up the connector, SITL, and only the
Flight Blender Compose stack started by that launcher. `--keep-provider` leaves
the provider running for a later connector restart.

The command uses an application factory, so importing connector code for tests
or diagnostics does not open the persistent SQLite database. The equivalent
direct Uvicorn command is:

```sh
uv run uvicorn 'utm_connector.api:create_app' --factory
```

Convenience targets are also available: `make setup`, `make doctor`, `make smoke`,
`make test`, `make run`, and `make demo`. They delegate to `uv run`, so they do not depend on
the Unix-specific `.venv/bin` layout.

The service listens on `http://127.0.0.1:8000`. Open the operator console at
`/ui/`; OpenAPI is available at `/docs`, and the health endpoint is
`/v1/health`.

The operator console is the recommended demo and user workflow. It shows
connector health, a readiness strip for the backend/vehicle link/diagnostics
configuration, vehicle telemetry, route geometry, mission validity, UTM
operation state, conformance, and recent events. It is intentionally served
from the connector with no external web assets, so it works on macOS, Linux,
and Windows in the same way as the API.

The mission picker accepts QGroundControl `.plan` files and Mission Planner
`.waypoints`/WPL 110 exports. Both are normalized into the same canonical
mission model; the UTM validity window and corridor are entered once in the
connector because neither GCS file format carries that provider metadata.

For GCS integration, start with the discovery endpoints:

```sh
curl http://127.0.0.1:8000/v1/capabilities
curl http://127.0.0.1:8000/v1/health
curl http://127.0.0.1:8000/v1/vehicles
```

`/v1/capabilities` describes supported mission formats, operator commands, the
provider declaration time-window rules, and the non-commanding MAVLink behavior.
The browser console uses those rules to reject stale Flight Blender windows
before submission. `/v1/vehicles` lists discovered vehicles,
telemetry freshness, active operation count, and the last session error when a
simulator or router cannot be reached. A `degraded` health status means at least
one configured MAVLink session or the selected UTM backend currently has an
error; `backend_error` contains the latest provider error when available.

For a clean disposable run, use this in `.env`:

```dotenv
UTM_CONNECTOR_STATE_DB_PATH=:memory:
UTM_CONNECTOR_MAVLINK_CONNECTIONS=[]
```

For a normal local run, keep the default SQLite path so operations and recent
telemetry survive a restart. If an old test operation makes the state confusing,
stop the connector and switch temporarily to `:memory:` rather than deleting
state while diagnosing the workflow. The API keeps the latest 1,000 events in
memory by default; the full event history remains in SQLite. Change
`UTM_CONNECTOR_EVENT_HISTORY_LIMIT` if a larger in-process window is needed.

## Connect a simulator over MAVLink

The connector can run one or more non-commanding MAVLink sessions in the background. Copy `.env.example` to `.env` and set the connection list to the URI exposed by your simulator or MAVLink router:

```dotenv
UTM_CONNECTOR_MAVLINK_CONNECTIONS=[{"vehicle_id":"sitl-1","connection_uri":"udpin:127.0.0.1:14551"}]
UTM_CONNECTOR_MAVLINK_POLL_INTERVAL_S=0.2
UTM_CONNECTOR_MAVLINK_RECONNECT_INTERVAL_S=5.0
```

Then start the connector with `uv run utm-connector` (or `make run`) and inspect live state at:

```sh
curl http://127.0.0.1:8000/v1/vehicles/sitl-1/status
```

The recommended real-world topology is one vehicle link into a MAVLink router,
with separate router endpoints for the GCS and connector. See
[`examples/mavlink-router/README.md`](../examples/mavlink-router/README.md).
The connector consumes telemetry and uses mission-protocol requests for drift
checking; it does not send vehicle-control commands. The separate-output SITL
shortcut below is still useful when a router is not installed. A vehicle link
that is unavailable at startup or drops later is retried automatically; the
operator console keeps the vehicle/link health visible while it reconnects.

### ArduPilot SITL and QGroundControl

For the shortest SITL-only path, use two simulator outputs so the GCS and
connector can observe the same vehicle independently:

```text
ArduPilot SITL --UDP 14550--> QGroundControl
                 --UDP 14551--> UTM connector
```

From the ArduPilot checkout, the standard `sim_vehicle.py` launcher works when
the ArduPilot Python tools are available:

```sh
ARDUPILOT_ROOT=/path/to/ardupilot
cd "$ARDUPILOT_ROOT"
PATH="$ARDUPILOT_ROOT/.venv/bin:$PATH" \
  ./Tools/autotest/sim_vehicle.py \
  -v ArduCopter -N \
  --out=udpout:127.0.0.1:14550 \
  --out=udpout:127.0.0.1:14551
```

If you already built the SITL target, the repository includes a dependency-free
launcher that works with the native executable on macOS, Linux, Windows, and
WSL. It uses the same two-output topology that was tested with QGroundControl
and the connector:

```sh
uv run python scripts/ardupilot_sitl.py --ardupilot-root "$ARDUPILOT_ROOT"
```

The helper expects `build/sitl/bin/arducopter` (or `.exe`). Build it once from
the ArduPilot checkout if needed:

```sh
./waf configure --board sitl
./waf copter -j2
```

Then start one GCS and the connector in separate terminals. Launch
QGroundControl or Mission Planner from the application menu; on macOS,
QGroundControl can also be started with:

```sh
open -a QGroundControl
```

From the connector checkout, use `uv run utm-connector` (or `make run` on
systems with `make`).

QGroundControl should show the SITL vehicle automatically. Then open
`http://127.0.0.1:8000/ui/` and use the operator console to load or create a
mission and run the operation lifecycle. The connector does not send vehicle
commands; it only consumes telemetry and uses mission-protocol requests when
onboard mission comparison is enabled. The connector state can also be
checked with:

```sh
curl http://127.0.0.1:8000/v1/vehicles/sitl-1/status
```

Mission Planner users can install the thin menu integration from
[`examples/mission-planner-plugin/`](../examples/mission-planner-plugin/).
Mission Planner remains the vehicle-facing GCS; the connector console handles
UTM declaration, authorization, conformance, and provider telemetry.

QGroundControl users can use the stock binary with the provider-neutral
contract and browser console. If the demo needs native UTM status inside Fly
View, use the optional custom-build overlay in
[`examples/qgroundcontrol-custom-build/`](../examples/qgroundcontrol-custom-build/);
it is not a runtime plugin for the stock binary.

The default local UTM is the connector's in-memory backend, so no external UTM service or account is required for the basic test loop. To use Flight Blender, set these values in `.env`:

```dotenv
UTM_CONNECTOR_BACKEND=flight-blender
UTM_CONNECTOR_FLIGHT_BLENDER_BASE_URL=http://127.0.0.1:8989
UTM_CONNECTOR_FLIGHT_BLENDER_BEARER_TOKEN=
UTM_CONNECTOR_FLIGHT_BLENDER_MAX_RETRIES=3
UTM_CONNECTOR_FLIGHT_BLENDER_RETRY_BACKOFF_S=0.25
UTM_CONNECTOR_RECORD_PATH=connector-events.jsonl
UTM_CONNECTOR_TELEMETRY_PUBLISH_INTERVAL_S=1.0
```

The adapter calls Flight Blender's `set_flight_declaration` endpoint with the generated WGS84 corridor and stores the provider declaration ID in the local operation record. It calls `set_telemetry` with the provider ID for subsequent telemetry. A mission whose altitude datum is AGL or AMSL is converted only when an explicit geoid grid is configured; otherwise submission is rejected because the connector does not have enough information to convert it to WGS84 safely.

For a live MAVLink vehicle, `GLOBAL_POSITION_INT.alt` is AMSL while Flight
Blender expects WGS84 ellipsoidal height. Set
`UTM_CONNECTOR_ALTITUDE_GEOID_GRID_PATH` to an explicitly installed PROJ
EGM96/EGM2008 grid to enable the coordinate-aware conversion. Without that
setting the connector preserves the source datum and refuses the provider
operation rather than silently treating AMSL as WGS84. AGL missions still need
a terrain/home reference and are rejected until one is supplied.

Inbound MAVLink remains event-driven, while provider telemetry is coalesced to
one publication per second by default. Set
`UTM_CONNECTOR_TELEMETRY_PUBLISH_INTERVAL_S=0` only for a backend or diagnostic
test that explicitly needs every snapshot.

If telemetry arrives before Flight Blender's declaration validity window opens,
the operation is shown as `DEGRADED` and the connector retries publication on
the next telemetry update. Once the provider accepts the stream it returns to
`ACTIVE`; deterministic configuration errors, such as a missing geoid grid,
remain terminal and are reported to the operator.

When a MAVLink link goes quiet, the runtime continues evaluating the last
observation until it becomes `STALE` or `LOST`. Those observations are retained
for diagnostics but are not forwarded to an active UTM operation; conformance
is reported as `TELEMETRY_UNRELIABLE` and publication is shown as `DEGRADED`.
Fresh telemetry automatically resumes publication after the link recovers.

When `UTM_CONNECTOR_RECORD_PATH` is set, connector events, backend request/response envelopes, and raw inbound MAVLink frames are appended as JSONL. Authorization headers are redacted. Raw frames are stored as base64 in `mavlink_frame` records, so the file remains portable and does not depend on a pymavlink dialect during capture. Recording is diagnostic-only: it never adds vehicle-control commands, and the file should be treated as sensitive telemetry.

Replay all connector records in a diagnostic tool with `JsonlReplay`:

```python
from utm_connector.recording import JsonlReplay

JsonlReplay("connector-events.jsonl").replay(lambda kind, payload: print(kind, payload))
```

To feed only the recorded MAVLink frames into a deterministic test harness:

```python
from utm_connector.recording import JsonlReplay

def inspect_frame(vehicle_id: str, frame: bytes) -> None:
    print(vehicle_id, len(frame), frame.hex())

JsonlReplay("connector-events.jsonl").replay_mavlink(inspect_frame)
```

The `/v1/capabilities` response reports `recording.configured` and
`recording.mavlink_raw`, while `/v1/integration` describes the stable record
type and replay entrypoint for a future GCS diagnostics panel.

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
