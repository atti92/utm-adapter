# QGCS UTM Adapter Project

## Local UTM Operations Connector

The repository includes working Phase 0, Phase 1, and the first Phase 2 slices from [`utm_connector_plan.md`](utm_connector_plan.md): a provider-neutral canonical model, loopback FastAPI API, deterministic in-memory UTM backend, Flight Blender HTTP adapter, non-commanding MAVLink normalization, QGroundControl `.plan` parsing, metre-correct corridor generation, mission drift classification, an operator console, and tests.

See [`docs/local-development.md`](docs/local-development.md) for setup and API examples.
For the complete Flight Blender + SITL + QGroundControl/Mission Planner path,
see [`docs/openutm-integration.md`](docs/openutm-integration.md).

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
without using the CLI.

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
Flight Blender reachability plus bearer-token authorization when that backend
is selected and the provider is available. The smoke test
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
