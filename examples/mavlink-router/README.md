# MAVLink Router topology

Use a router when a vehicle has one physical telemetry link but multiple
software consumers need the same MAVLink stream. The vehicle connects to the
router once; the router fans out traffic to QGroundControl, Mission Planner,
and the UTM connector.

```text
vehicle UART / SITL UDP 14560
              |
              v
       mavlink-routerd
          |        |
          v        v
   GCS UDP 14550  connector UDP 14551
```

The connector is a non-commanding MAVLink consumer: it normalizes telemetry
and can request the onboard mission for drift checking, but it does not send
arm, takeoff, landing, or navigation commands. The router forwards those
MAVLink protocol packets back to the vehicle when mission download is used.

## Local SITL

The checked-in `main.conf` uses the router's UDP server on port `14560` and
two normal UDP output endpoints. Start the router with the configuration file:

```sh
mavlink-routerd -c examples/mavlink-router/main.conf
```

From the connector checkout, validate the fan-out contract before starting
the live stack:

```sh
make router-check
uv run python scripts/check_mavlink_router.py --strict
```

The first command validates the endpoint contract on every platform. The
strict form requires a usable runtime: it accepts either a native
`mavlink-routerd` or the Docker fallback. Use
`--router-runtime native` to require the host binary, or
`--router-runtime docker --router-source-root PATH` to check the portable
fallback explicitly.

### Cross-platform Docker fallback

The router is normally installed on the Linux companion computer that owns the
vehicle telemetry link. For a local macOS or Windows demonstration, Docker can
build and run the same router binary. Keep a checkout beside this repository
(`../mavlink-router`) or set `MAVLINK_ROUTER_ROOT`, then use the supervised
launcher:

```sh
make demo-check
uv run python scripts/openutm_demo.py --topology router --router-runtime docker --gcs qgroundcontrol
```

The first run builds `utm-adapter-mavlink-router:local` from the router
checkout and caches it in Docker. The launcher publishes only the vehicle input
port and sends the two consumer streams back to the host, so QGroundControl
and the connector continue to use their normal UDP ports. Use
`--router-runtime native` to require a host-installed binary.

For the supervised Flight Blender demo, the same topology is started with:

```sh
uv run python scripts/openutm_demo.py --topology router --gcs qgroundcontrol
```

The launcher starts Flight Blender, the connector, the router, and ArduPilot
SITL as one managed session. Run `--check` first when preparing a new machine.
For a real aircraft, the router executable belongs on the companion computer
that owns the vehicle link; the Docker fallback is intended for local demos.

For a manual SITL setup, start ArduPilot with one output to the router:

```sh
./Tools/autotest/sim_vehicle.py \
  -v ArduCopter -N \
  --custom-location=47.4979,19.0402,0,0 \
  --out=udpout:127.0.0.1:14560
```

Run the connector with one router endpoint:

```dotenv
UTM_CONNECTOR_MAVLINK_CONNECTIONS=[{"vehicle_id":"sitl-1","connection_uri":"udpin:127.0.0.1:14551"}]
```

The connector currently maps one configured vehicle session to one router
output. For a multi-vehicle fleet, add a separate router output and connector
URI for each vehicle; repeating one `udpin:` URI for multiple vehicle IDs is
rejected during startup so a fleet cannot appear healthy while sessions are
silently competing for the same stream.

The connector retries this endpoint automatically when the router or vehicle
is temporarily unavailable. Set `UTM_CONNECTOR_MAVLINK_RECONNECT_INTERVAL_S`
to change the retry interval (the default is five seconds).

Then open `http://127.0.0.1:8000/ui/` for the operator console and start
QGroundControl or Mission Planner normally. The connector can open a physical
serial link directly with `serial:/dev/ttyUSB0:57600` on Linux/macOS or
`serial:COM3:57600` on Windows. The recommended deployment is still to give
that one serial link to `mavlink-routerd` on the companion computer and point
the connector at the router's `udpin:` output.

The quick `--out=14550` plus `--out=14551` SITL setup remains useful for a
minimal simulator test, but it is not the recommended physical-drone
topology. A real aircraft does not need two MAVLink ports: use one telemetry
link to a companion-computer router and let that router expose separate
consumer endpoints.
