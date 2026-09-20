# Manual openUTM integration test

This is the complete local path for testing ArduPilot or PX4 SITL, a ground-control
station (QGroundControl or Mission Planner), the connector's operator console,
and Flight Blender.
The connector itself is cross-platform; Docker, SITL, and GCS installation
steps remain dependent on the operating system.

The examples use loopback addresses and the Budapest test location
`47.4979,19.0402`. Change the location passed to SITL and the mission generator
together if you want to test somewhere else.

## Prerequisites and checkout paths

Install `uv`, Docker, and one GCS. Clone the Flight Blender and ArduPilot
repositories separately when using ArduPilot. PX4 can use the official Docker
SITL image and does not require a PX4 checkout for the supervised demo. Keep
the connector, Flight Blender, and SITL in separate terminals so each process
can be stopped independently.

In macOS, Linux, or WSL, set the checkout paths once per terminal session:

```sh
export UTM_ADAPTER_ROOT="/path/to/utm-adapter"
export FLIGHT_BLENDER_ROOT="/path/to/flight-blender"
export ARDUPILOT_ROOT="/path/to/ardupilot"
```

In Windows PowerShell, use:

```powershell
$env:UTM_ADAPTER_ROOT = "C:\path\to\utm-adapter"
$env:FLIGHT_BLENDER_ROOT = "C:\path\to\flight-blender"
$env:ARDUPILOT_ROOT = "C:\path\to\ardupilot"
```

The paths are deliberately variables so this guide can be copied to another
machine without editing every command. The SITL command below assumes a
POSIX-like shell (macOS, Linux, or WSL). Native Windows users can run SITL in
WSL, or use the Mission Planner SITL launcher, while running the connector from
PowerShell.

## Recommended supervised demo

The repository includes a cross-platform Python launcher that removes the
multi-terminal startup ceremony while preserving the same topology:

```sh
uv run python scripts/openutm_demo.py --check
uv run python scripts/openutm_demo.py
```

It starts Flight Blender, the connector, and ArduPilot SITL, opens the
operator console, and auto-detects QGroundControl. On Windows PowerShell use
the same commands and add `--gcs mission-planner` when Mission Planner is the
selected GCS. Use `--no-browser` or `--gcs none` when those applications are
already open. Press Ctrl+C to cleanly stop the simulator, connector, and
provider stack owned by the launcher. The detailed commands below remain
available for diagnosing individual components or testing a router topology.

For PX4, use the same supervised launcher without an extra checkout:

```sh
uv run python scripts/openutm_demo.py --simulator px4 --check
uv run python scripts/openutm_demo.py --simulator px4
```

The first PX4 run pulls `px4io/px4-sitl:latest` if it is not already cached.
The launcher maps PX4's documented remote GCS port 14550 to the host GCS port
14550 and remote external-API port 14540 to the connector's host port 14540.
PX4 is started before the connector so Docker can claim the published UDP
endpoint first, after which the connector attaches to the same host/remote
pairing. Pass `--px4-image IMAGE` to pin an approved image.

## Start Flight Blender

Use the local-development configuration from the Flight Blender checkout. This
configuration enables standalone mode and bypasses token verification for local
testing only.

macOS, Linux, or WSL:

```sh
cd "$FLIGHT_BLENDER_ROOT"
cp deployment_support/.env.local .env
docker build . -t openutm/flight-blender-dev
docker compose -f docker-compose-dev.yml up -d
curl http://127.0.0.1:8000/ping
```

Windows PowerShell:

```powershell
Set-Location $env:FLIGHT_BLENDER_ROOT
Copy-Item deployment_support\.env.local .env
docker build . -t openutm/flight-blender-dev
docker compose -f docker-compose-dev.yml up -d
curl.exe http://127.0.0.1:8000/ping
```

On an Apple Silicon Mac, the Compose file requests `linux/amd64`; Docker
Desktop may use emulation and the first build can take several minutes. Do not
use `BYPASS_AUTH_TOKEN_VERIFICATION=1` outside this isolated development
environment.

## Start SITL and a GCS

For a quick SITL test, use two UDP outputs so the GCS and connector can observe
the same vehicle independently:

```text
ArduPilot SITL --UDP 14550--> QGroundControl or Mission Planner
                 --UDP 14551--> UTM connector
```

macOS, Linux, or WSL:

```sh
cd "$ARDUPILOT_ROOT"
PATH="$ARDUPILOT_ROOT/.venv/bin:$PATH" \
  ./Tools/autotest/sim_vehicle.py \
  -v ArduCopter -N \
  --custom-location=47.4979,19.0402,0,0 \
  --out=udpout:127.0.0.1:14550 \
  --out=udpout:127.0.0.1:14551
```

When the ArduCopter SITL target is already built, use the connector checkout's
native-binary helper instead of `sim_vehicle.py`:

```sh
uv run python "$UTM_ADAPTER_ROOT/scripts/ardupilot_sitl.py" \
  --ardupilot-root "$ARDUPILOT_ROOT"
```

It starts the same two outputs and places the vehicle at the documented
Budapest test location by default. Pass `--home lat,lon,altitude,heading` to
use another location.

The supervised demo also accepts `--gcs-udp-port` and
`--connector-udp-port` when the default simulator ports are already in use.

PX4's equivalent topology is supplied by its two documented MAVLink UDP
endpoints:

```text
PX4 SITL remote 14550 -> host 14550 -> QGroundControl or Mission Planner
PX4 SITL remote 14540 -> host 14540 -> UTM connector
```

Run it with:

```sh
uv run python "$UTM_ADAPTER_ROOT/scripts/px4_sitl.py"
```

The helper uses the official `px4io/px4-sitl:latest` image and publishes both
UDP endpoints on macOS, Linux, WSL, and Windows. For a native PX4 checkout,
pass `--local-binary --px4-root PATH` after building the desired PX4 SITL
target with the PX4 project tools.

Start exactly one GCS on UDP `14550` for the simplest setup. Launch
QGroundControl or Mission Planner normally from its application menu. On
macOS, QGroundControl can also be started with `open -a QGroundControl`; on
Linux, use the installed `qgroundcontrol` command if available. Mission Planner
is normally used on Windows. If both GCS applications must observe the same
vehicle, use a MAVLink router instead of binding both directly to the same UDP
port.

QGroundControl or Mission Planner should show the SITL vehicle. The connector
is non-commanding: it consumes telemetry and can issue mission-protocol
requests for drift checking, but it does not send vehicle-control commands.
Open `http://127.0.0.1:8001/ui/` after starting the connector and use that
console for the operator-facing mission and operation flow.

For a physical vehicle, or when more than one GCS must share a single vehicle
link, use the router topology in
[`examples/mavlink-router/README.md`](../examples/mavlink-router/README.md)
instead of assigning multiple physical MAVLink ports on the aircraft.

For Mission Planner, the optional thin plugin in
[`examples/mission-planner-plugin/`](../examples/mission-planner-plugin/) adds
an operator-console menu and a connector health check without sending vehicle
control messages. It keeps the standalone connector default on port `8000`, and
automatically discovers the full-stack demo connector on `8001` when Flight
Blender occupies `8000`.

## Start the connector against Flight Blender

The connector uses port `8001` because Flight Blender's development Compose
file uses port `8000`. Generate a fresh operation ID for each run so a restart
cannot collide with an old SQLite record.

macOS, Linux, or WSL:

```sh
cd "$UTM_ADAPTER_ROOT"
export OPERATION_ID="$(uv run python -c 'import uuid; print(uuid.uuid4())')"
export UTM_CONNECTOR_PORT=8001
export UTM_CONNECTOR_BACKEND=flight-blender
export UTM_CONNECTOR_FLIGHT_BLENDER_BASE_URL=http://127.0.0.1:8000
export UTM_CONNECTOR_FLIGHT_BLENDER_BEARER_TOKEN="$(uv run python scripts/generate_flight_blender_dev_token.py)"
export UTM_CONNECTOR_FLIGHT_BLENDER_SUBMITTED_BY=connector@example.invalid
export UTM_CONNECTOR_RECORD_PATH=.local/connector-events.jsonl
# Required for AMSL MAVLink telemetry -> Flight Blender WGS84 conversion.
export UTM_CONNECTOR_ALTITUDE_GEOID_GRID_PATH=/path/to/us_nga_egm96_15.tif
uv run utm-connector
```

Windows PowerShell:

```powershell
Set-Location $env:UTM_ADAPTER_ROOT
$env:OPERATION_ID = (uv run python -c "import uuid; print(uuid.uuid4())").Trim()
$env:UTM_CONNECTOR_PORT = "8001"
$env:UTM_CONNECTOR_BACKEND = "flight-blender"
$env:UTM_CONNECTOR_FLIGHT_BLENDER_BASE_URL = "http://127.0.0.1:8000"
$env:UTM_CONNECTOR_FLIGHT_BLENDER_BEARER_TOKEN = (uv run python scripts/generate_flight_blender_dev_token.py).Trim()
$env:UTM_CONNECTOR_FLIGHT_BLENDER_SUBMITTED_BY = "connector@example.invalid"
$env:UTM_CONNECTOR_RECORD_PATH = ".local\connector-events.jsonl"
$env:UTM_CONNECTOR_ALTITUDE_GEOID_GRID_PATH = "C:\path\to\us_nga_egm96_15.tif"
uv run utm-connector
```

The `.local` directory is ignored by Git and is created automatically when the
mission generator or recorder needs it. For repeated runs, put the same values
in a local `.env` file instead of exporting them. Never commit the generated
development token.

Check both services from another terminal. On Windows, use `curl.exe` rather
than the PowerShell `curl` alias:

```sh
curl http://127.0.0.1:8000/ping
curl http://127.0.0.1:8001/v1/health
curl http://127.0.0.1:8001/v1/capabilities
curl http://127.0.0.1:8001/v1/vehicles
```

The vehicle directory may be empty until the first MAVLink heartbeat arrives.
If the connector cannot reach the simulator, `/v1/health` reports `degraded`
and `/v1/vehicles` includes the last session error.

## Submit and activate a declaration

Generate an immediately active mission and submit it immediately. Flight
Blender uses WGS84 ellipsoidal height while MAVLink global position altitude is
AMSL, so configure `UTM_CONNECTOR_ALTITUDE_GEOID_GRID_PATH` with a host-
installed PROJ EGM96/EGM2008 grid for a real SITL or aircraft run. The
connector converts mission and telemetry values using latitude/longitude and
retains the source datum in local vehicle state. If the grid is absent,
submission is rejected safely; the connector never guesses an altitude
conversion. AGL still requires a terrain/home reference and is rejected until
one is provided.
The `181 m` center in the example matches the supplied Budapest SITL home after
EGM96 conversion; choose a center and span appropriate for another simulator or
vehicle home.

macOS, Linux, or WSL:

```sh
cd "$UTM_ADAPTER_ROOT"
export MISSION_FILE="$UTM_ADAPTER_ROOT/.local/flight-blender-mission.json"
uv run python scripts/generate_test_mission.py \
  --output "$MISSION_FILE" \
  --latitude 47.4979 --longitude 19.0402 \
  --altitude-m 181 --altitude-span-m 4

curl -X PUT http://127.0.0.1:8001/v1/missions/sitl-1 \
  -H 'content-type: application/json' \
  --data-binary @"$MISSION_FILE"

curl -X POST 'http://127.0.0.1:8001/v1/operator-intents?vehicle_id=sitl-1' \
  -H 'content-type: application/json' \
  -d "{\"schema_version\":\"1.0\",\"command\":\"SUBMIT_OPERATION\",\"operation_id\":\"$OPERATION_ID\"}"

sleep 7

curl -X POST 'http://127.0.0.1:8001/v1/operator-intents?vehicle_id=sitl-1' \
  -H 'content-type: application/json' \
  -d "{\"schema_version\":\"1.0\",\"command\":\"START_OPERATION\",\"operation_id\":\"$OPERATION_ID\"}"
```

Windows PowerShell:

```powershell
Set-Location $env:UTM_ADAPTER_ROOT
$env:MISSION_FILE = Join-Path $env:UTM_ADAPTER_ROOT ".local\flight-blender-mission.json"
uv run python scripts/generate_test_mission.py --output $env:MISSION_FILE --latitude 47.4979 --longitude 19.0402 --altitude-m 181 --altitude-span-m 4

curl.exe -X PUT http://127.0.0.1:8001/v1/missions/sitl-1 `
  -H "content-type: application/json" --data-binary "@$env:MISSION_FILE"

$submitBody = '{"schema_version":"1.0","command":"SUBMIT_OPERATION","operation_id":"' + $env:OPERATION_ID + '"}'
curl.exe -X POST "http://127.0.0.1:8001/v1/operator-intents?vehicle_id=sitl-1" `
  -H "content-type: application/json" -d $submitBody

Start-Sleep -Seconds 7

$startBody = '{"schema_version":"1.0","command":"START_OPERATION","operation_id":"' + $env:OPERATION_ID + '"}'
curl.exe -X POST "http://127.0.0.1:8001/v1/operator-intents?vehicle_id=sitl-1" `
  -H "content-type: application/json" -d $startBody
```

The submit response contains `provider_operation_id`, the Flight Blender
declaration ID. The start request changes the provider declaration to the
activated state. Once the declaration is active, SITL telemetry is forwarded to
Flight Blender's Remote ID telemetry endpoint.

Inspect the connector's canonical state, conformance assessment, and recorded
provider exchanges. Substitute `$OPERATION_ID` with the PowerShell environment
variable `$env:OPERATION_ID` when using PowerShell:

```sh
curl http://127.0.0.1:8001/v1/operations/$OPERATION_ID
curl http://127.0.0.1:8001/v1/vehicles/sitl-1/status
curl http://127.0.0.1:8001/v1/events
tail -n 10 .local/connector-events.jsonl
```

The vehicle should initially be `CONFORMING` while it is inside the generated
corridor. Move the simulated vehicle outside the route in the GCS or change the
onboard mission, then use:

```sh
curl -X POST http://127.0.0.1:8001/v1/vehicles/sitl-1/onboard-mission/refresh
curl -X POST http://127.0.0.1:8001/v1/operations/$OPERATION_ID/refresh
```

The next MAVLink mission read is classified in `mission_drift`. A provider
state refresh is available with the second command.

## Optional verification suite

For the openUTM verification scenarios, set `VERIFICATION_ROOT` to the
verification checkout and use its dedicated environment and current Compose
file. It has its own Flight Blender service on port `8000`, so stop the
development Compose stack first or change the host port before starting both.

```sh
cd "$VERIFICATION_ROOT"
uv sync --locked --all-extras --dev
docker compose --env-file tests/.env.tests -f tests/docker-compose.fb.yml up -d --wait
uv run openutm-verify --debug --config config/pull_request.yaml
docker compose --env-file tests/.env.tests -f tests/docker-compose.fb.yml down
```

## Cleanup and failure tests

Stop the connector and SITL with `Ctrl+C` in their terminals, then tear down
Flight Blender:

```sh
cd "$FLIGHT_BLENDER_ROOT"
docker compose -f docker-compose-dev.yml down
```

To test retry and diagnostics, stop Flight Blender while the connector is
running and submit telemetry or refresh an operation. The connector should
return HTTP `502` after its configured retries, leave the last successful local
state intact, and record provider request/response envelopes without recording
bearer-token values.
