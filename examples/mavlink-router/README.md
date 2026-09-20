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
strict form also checks that `mavlink-routerd` is installed and on `PATH`.

For the supervised Flight Blender demo, the same topology is started with:

```sh
uv run python scripts/openutm_demo.py --topology router --gcs qgroundcontrol
```

The launcher starts Flight Blender, the connector, `mavlink-routerd`, and
ArduPilot SITL as one managed session. Run `--check` first when preparing a
new machine. The router executable must be installed on the demo host (or on
the companion computer that owns the vehicle link for a real aircraft).

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

The connector retries this endpoint automatically when the router or vehicle
is temporarily unavailable. Set `UTM_CONNECTOR_MAVLINK_RECONNECT_INTERVAL_S`
to change the retry interval (the default is five seconds).

Then open `http://127.0.0.1:8000/ui/` for the operator console and start
QGroundControl or Mission Planner normally. The router endpoint pattern also
applies to a physical vehicle: replace the SITL UDP input with the vehicle's
serial telemetry device, for example `/dev/ttyUSB0:57600` on Linux/macOS.

The quick `--out=14550` plus `--out=14551` SITL setup remains useful for a
minimal simulator test, but it is not the recommended physical-drone
topology. A real aircraft does not need two MAVLink ports: use one telemetry
link to a companion-computer router and let that router expose separate
consumer endpoints.
