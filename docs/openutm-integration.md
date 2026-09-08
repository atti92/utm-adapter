# Manual openUTM integration test

This is the complete local path for testing ArduPilot SITL, QGroundControl,
the connector, and Flight Blender. It uses Docker for Flight Blender and keeps
the connector on port `8001` because Flight Blender's local Compose file binds
port `8000`.

## Start Flight Blender

Use the local-development configuration from the openUTM Flight Blender
checkout. The configuration enables standalone mode and bypasses token
verification for local testing only.

```sh
cd /Users/atti/repos/flight-blender
cp deployment_support/.env.local .env
docker build . -t openutm/flight-blender-dev
docker compose -f docker-compose-dev.yml up -d
curl http://127.0.0.1:8000/ping
```

On an Apple Silicon Mac, the Compose file requests `linux/amd64`; Docker
Desktop may use emulation and the first build can take several minutes. Do not
use `BYPASS_AUTH_TOKEN_VERIFICATION=1` outside this isolated development
environment.

## Start SITL and QGroundControl

In a separate terminal, start ArduCopter with two UDP outputs:

```sh
cd /Users/atti/repos/ardupilot
PATH="/Users/atti/repos/ardupilot/.venv/bin:$PATH" \
  ./Tools/autotest/sim_vehicle.py \
  -v ArduCopter -N \
  --custom-location=47.4979,19.0402,0,0 \
  --out=udpout:127.0.0.1:14550 \
  --out=udpout:127.0.0.1:14551
```

Start QGroundControl in another terminal:

```sh
open -a QGroundControl
```

QGroundControl should discover the vehicle on UDP `14550`.

## Start the connector against Flight Blender

The connector consumes the second SITL stream on UDP `14551` and exposes its
own API on `8001`:

```sh
cd /Users/atti/repos/utm-adapter
UTM_CONNECTOR_PORT=8001 \
UTM_CONNECTOR_BACKEND=flight-blender \
UTM_CONNECTOR_FLIGHT_BLENDER_BASE_URL=http://127.0.0.1:8000 \
UTM_CONNECTOR_FLIGHT_BLENDER_BEARER_TOKEN=local-development-token \
UTM_CONNECTOR_RECORD_PATH=connector-events.jsonl \
uv run utm-connector
```

Check both services:

```sh
curl http://127.0.0.1:8000/ping
curl http://127.0.0.1:8001/v1/health
curl http://127.0.0.1:8001/v1/vehicles/sitl-1/status
```

## Submit and activate a declaration

Generate a future WGS84 mission. The WGS84 datum is intentional: the connector
does not guess a conversion from QGroundControl's AGL/AMSL mission altitude.

```sh
uv run python scripts/generate_test_mission.py \
  --output /tmp/utm-adapter-flight-blender-mission.json \
  --latitude 47.4979 --longitude 19.0402
```

Submit it and capture the returned operation ID:

```sh
curl -X PUT http://127.0.0.1:8001/v1/missions/sitl-1 \
  -H 'content-type: application/json' \
  --data-binary @/tmp/utm-adapter-flight-blender-mission.json

curl -X POST 'http://127.0.0.1:8001/v1/operator-intents?vehicle_id=sitl-1' \
  -H 'content-type: application/json' \
  -d '{"schema_version":"1.0","command":"SUBMIT_OPERATION","operation_id":"00000000-0000-0000-0000-000000000001"}'

curl -X POST 'http://127.0.0.1:8001/v1/operator-intents?vehicle_id=sitl-1' \
  -H 'content-type: application/json' \
  -d '{"schema_version":"1.0","command":"START_OPERATION","operation_id":"00000000-0000-0000-0000-000000000001"}'
```

The submit response contains `provider_operation_id`, the Flight Blender
declaration ID. The start request changes the provider declaration to the
activated state. Once the declaration is active, SITL telemetry is forwarded
to Flight Blender's Remote ID telemetry endpoint.

Inspect the connector's canonical state, conformance assessment, and recorded
provider exchanges:

```sh
curl http://127.0.0.1:8001/v1/operations/00000000-0000-0000-0000-000000000001
curl http://127.0.0.1:8001/v1/vehicles/sitl-1/status
curl http://127.0.0.1:8001/v1/events
tail -n 10 connector-events.jsonl
```

The vehicle should initially be `CONFORMING` while it is inside the generated
corridor. Move the simulated vehicle outside the route in QGroundControl or
change the onboard mission, then use:

```sh
curl -X POST http://127.0.0.1:8001/v1/vehicles/sitl-1/onboard-mission/refresh
```

The next MAVLink mission read is classified in `mission_drift`. A provider
state refresh is available with:

```sh
curl -X POST http://127.0.0.1:8001/v1/operations/00000000-0000-0000-0000-000000000001/refresh
```

## Optional verification suite

For the openUTM verification scenarios, use the verification repository's
dedicated environment and its current Compose file. It has its own Flight
Blender service on port `8000`, so stop the development Compose stack first or
change the host port before starting both.

```sh
cd /Users/atti/repos/verification
uv sync --locked --all-extras --dev
docker compose --env-file tests/.env.tests -f tests/docker-compose.fb.yml up -d --wait
uv run openutm-verify --debug --config config/pull_request.yaml
docker compose --env-file tests/.env.tests -f tests/docker-compose.fb.yml down
```

## Cleanup and failure tests

Stop the three local processes, then tear down Flight Blender:

```sh
cd /Users/atti/repos/flight-blender
docker compose -f docker-compose-dev.yml down
```

To test retry and diagnostics, stop Flight Blender while the connector is
running and submit telemetry or refresh an operation. The connector should
return HTTP `502` after its configured retries, leave the last successful local
state intact, and record the provider request/response envelopes without
recording bearer-token values.
