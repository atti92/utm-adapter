# QGCS UTM Adapter Project

## Local UTM Operations Connector

The repository contains the working connector, operator console, provider adapter,
non-commanding MAVLink integration, QGroundControl and Mission Planner mission
imports, onboard-mission drift checks, and supervised Flight Blender/SITL demo
paths described in [`utm_connector_plan.md`](utm_connector_plan.md). The
implementation is intentionally GCS-first: operators use the browser console
for UTM workflow while QGroundControl or Mission Planner remains the vehicle
control application.

See [`docs/local-development.md`](docs/local-development.md) for setup and API examples.
For the complete Flight Blender + SITL + QGroundControl/Mission Planner path,
see [`docs/openutm-integration.md`](docs/openutm-integration.md).
For a presentation-ready checklist with the operator flow and real-drone
topology, see [`docs/demo-runbook.md`](docs/demo-runbook.md).

The minimum local setup is Python 3.11–3.13 and `uv`. Add Docker Desktop (or
Docker Engine with Compose) for the Flight Blender demo. The browser operator
console is the cross-platform UTM interface; QGroundControl is optional on
macOS/Linux/Windows, while Mission Planner is an optional Windows-only GCS
integration. Run `make demo-check` before a demo to get actionable setup
guidance and the correct start command for ArduPilot or PX4.

The local runtime can also consume non-commanding MAVLink telemetry from a configured simulator or MAVLink router. For a physical vehicle, use the router topology in [`examples/mavlink-router/README.md`](examples/mavlink-router/README.md) so the connector and GCS share one vehicle link.

```sh
uv sync
uv run python scripts/doctor.py
uv run python scripts/local_smoke.py
uv run pytest
uv run utm-connector
```

For the shortest operator-facing demo, use `uv run utm-connector --demo --open-browser`
or `make demo`; the default browser opens the console automatically and a
moving demo vehicle is supplied. The
operator console is designed for the normal demo flow: select a vehicle, load
a QGroundControl `.plan`, Mission Planner `.waypoints`, or demo route,
validate it, submit/start the operation, and watch telemetry and conformance
without using the CLI. It can also read a route already uploaded from the
vehicle by QGroundControl or Mission Planner and import it after the operator
supplies explicit UTM metadata.

For a full Flight Blender + SITL demonstration with the operator-facing GCS
path, use the safe one-time bootstrap command below. It installs the locked
Python environment and clones only missing dependencies beside this checkout;
existing simulator directories are validated and reused without pulling,
resetting, or overwriting local work:

```sh
uv run python scripts/setup_demo.py
# or: make demo-setup
```

Add `--build-ardupilot` when the ArduCopter SITL binary is not already built;
the build is intentionally opt-in because it can take several minutes. The
PX4 Docker path needs no ArduPilot or PX4 checkout, and can be prepared with
`uv run python scripts/setup_demo.py --simulator px4`. Add
`--topology router` to also prepare the MAVLink Router source used by the
single-link physical-drone-style demo. Set `FLIGHT_BLENDER_ROOT`,
`ARDUPILOT_ROOT`, or `MAVLINK_ROUTER_ROOT` when using non-default paths.

The `openutm_demo.py --check` command reports any missing build or runtime
prerequisite before startup.
The
launcher prepares Flight Blender's local environment, starts the provider,
connector, and simulator, opens the operator console, and detects an installed
QGroundControl or Mission Planner (QGroundControl first, then Mission Planner
on Windows). Use `--simulator px4` to use the official cross-platform PX4
SITL container instead; PX4's normal GCS stream stays on UDP 14550 and its
external-API stream feeds the connector on UDP 14540. Both simulator paths
honor the shared `--home lat,lon,altitude,heading` option. Use `--check` to
validate prerequisites without starting anything. Press Ctrl+C to stop the simulator,
connector, and provider stack started by that run.

To launch a locally built QGroundControl app, pass its executable explicitly;
the same option works on macOS, Linux, and Windows and can be stored in
`QGROUNDCONTROL_COMMAND` for a repeatable demo setup:

```sh
uv run python scripts/openutm_demo.py --gcs qgroundcontrol \
  --qgroundcontrol-command \
  "/path/to/Custom-QGroundControl --demo"
```

Before a presentation, run `make gcs-demo-check` (or `make demo-check` for the
broader host inventory). It validates the required
Flight Blender/SITL/Docker path and reports optional QGroundControl, Mission
Planner, and MAVLink Router availability separately, so a missing native app
does not obscure whether the browser-based demo is ready.
Use `make gcs-demo-verify` to start the split-topology demo, launch the detected
GCS, confirm that it stays running, and exercise the connector lifecycle before
cleaning everything up. `make gcs-router-demo-verify` performs the same check
with the single-link MAVLink Router topology used to model a physical vehicle.

For a locally built QGroundControl with the UTM Fly View card, set its executable
once and use the dedicated targets below. The value may include quoted arguments
such as `--demo`:

```sh
export QGROUNDCONTROL_COMMAND="/path/to/Custom-QGroundControl"
make gcs-custom-qgc-demo-check
make gcs-custom-qgc-demo
# automated start, process, MAVLink, and connector-lifecycle verification:
make gcs-custom-qgc-demo-verify
```

These targets select only the custom QGroundControl binary; the simulator and
connector workflow stays identical to the standard GCS demo.

For a physical-drone-style single telemetry link, use the supervised fan-out
demo. It prefers a host-installed `mavlink-routerd`; when that is unavailable,
it can build and run the router in Docker (the default on macOS/Windows):

```sh
make gcs-router-demo-check
make gcs-router-demo
```

ArduPilot emits one MAVLink stream to the router; the router exposes the
standard UDP endpoints for the GCS and connector. Set
`MAVLINK_ROUTER_ROOT` when the router checkout is not the sibling
`../mavlink-router` directory, or force a runtime with
`--router-runtime native` or `--router-runtime docker`. The default split
topology remains the simplest cross-platform SITL path when a single-link
router is not needed.

For the shortest cross-platform full-stack demo, use PX4's official Docker SITL
image, which does not require an ArduPilot checkout:

```sh
make integration-demo-px4-check
make integration-demo-px4
# optional automated lifecycle verification (starts and stops its own stack)
make integration-demo-px4-verify
# the same verification against the native ArduPilot SITL checkout
make integration-demo-verify
```

The verification target is for demo preparation and regression checks. It
validates the live vehicle/provider/connector lifecycle through the same API
used by the operator console and passively confirms that a vehicle heartbeat
reaches the GCS UDP endpoint; it is not required for normal operator use.

The service root also opens the console directly at
[http://127.0.0.1:8000/](http://127.0.0.1:8000/).

The portable host-side boundary is documented in
[docs/gcs-client.md](docs/gcs-client.md); it is suitable for a thin Mission
Planner or QGroundControl adapter without moving provider logic into the GCS.
Mission Planner users can use the optional menu plugin in
[examples/mission-planner-plugin](examples/mission-planner-plugin), while
QGroundControl users can use the zero-fork manifest and browser console, or
the optional native Fly View overlay in
[examples/qgroundcontrol-custom-build](examples/qgroundcontrol-custom-build)
when producing a QGroundControl custom build.

The `--demo` flag creates a clearly named `demo-sitl` vehicle with moving
sample telemetry through the same connector path as MAVLink input. It is
disabled by default and only affects that process; live runs continue to use
the configured backend and MAVLink sessions.

The doctor checks the active Python/configuration, writable local state, and
Flight Blender reachability plus bearer-token or OAuth authorization when that
backend is selected and the provider is available. OAuth client secrets may
be loaded from the optional host OS credential-store integration; run
`uv sync --extra credentials` and
`uv run --extra credentials python scripts/credential_store.py --help` for
setup. The smoke test
exercises mission upload, operation submission, start, telemetry, conformance,
and completion entirely in-process. Neither command starts a background
simulator or requires Flight Blender credentials. These commands
work on Linux, macOS, and Windows when run from a shell with `uv` installed.

The `utm-connector` command starts the API through an application factory, so
persistent state is opened only when the service is actually started. If you
run Uvicorn directly, use the equivalent factory form:

```sh
uv run uvicorn 'utm_connector.api:create_app' --factory
```

For a disposable configuration that cannot reuse old local state, set
`UTM_CONNECTOR_STATE_DB_PATH=:memory:` in `.env`. For persistent local state,
copy the tracked template first:

```sh
cp .env.example .env       # macOS/Linux
copy .env.example .env     # Windows Command Prompt
```

`uv sync` installs the pinned geospatial dependencies used by the corridor engine. The project supports Python 3.10 through 3.13. Python 3.10 is a transitional compatibility target only and should be removed when its upstream security-support window closes in October 2026.

CI exercises Python 3.11–3.13 on Linux and Python 3.13 on macOS and Windows. The connector uses loopback networking, SQLite, `httpx`, and `pymavlink` without OS-specific code paths; simulator/GCS binaries remain platform-specific test dependencies.

## Goal
The goal of this work is to develop a UTM focused working group within Dronecode membership and build an open / configurable adapter for QGCS to enable it to exchange relevant data with a UTM system. The adapter would be configurable so that drone operators can specify what UTM system/service provider they want to use. The UTM system in turn must implement those APIs to exchange data with QGCS. 
## Scope

![Screenshot](images/net-rid.jpg)

Figure: Image depicting the scope of ASTM Network RID standard, the part in Red: the way operators submit data to the UTM system is not standardized and we hope to build an API specification and a configurable implementation for network identification as well as other relevant data (flight authorizations, traffic information, geozones, conformance alerts etc.). 

## Deliverables

1. OpenAPI document specifying the adapter + relevant documentation of configuring adapter 
2. API to be implemented at the UTM Service Provider side
3. Implement Adapter + configuration file in QGCS that enables exchange of data with different UTM services
4. Integration of this adapter in QGCS builds + test infrastructure
 
## Timeline
- Start date: 31 May 2023 -  30 November 2023 (6 months)
- Evaluation phase: December + January 2023 / re-work

## Meetings

- :calendar: Bi-Weekly Meeting Thursdays 4:30 PM CET | 7:30 AM PT [Meeting Minutes](meeting-minutes.md)
- :link: Meeting Link: https://discord.gg/smTaq2rRVt
