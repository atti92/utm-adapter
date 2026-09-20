# UTM connector demo runbook

This is the shortest repeatable path for a presentation. The browser console
handles the UTM workflow; QGroundControl or Mission Planner remains the normal
vehicle-control application.

## One-time preparation

From the repository root:

```sh
uv run python scripts/setup_demo.py
uv run python scripts/check_demo.py
```

The setup command installs the locked Python environment and clones only
missing Flight Blender and ArduPilot checkouts beside this repository. A newly
cloned ArduPilot checkout includes its recursive submodules, as required by
the Waf build. It reuses existing directories without pulling, resetting,
updating submodules, or overwriting local work. Add `--build-ardupilot` if the
SITL binary has not been built yet; for an existing checkout, setup performs a
read-only submodule preflight and prints the initialization command if modules
are missing. The
full demo also needs Docker Desktop (or Docker Engine with Compose). The
browser-only demo needs only `uv`.

For the optional native GCS integrations:

- QGroundControl works on macOS, Linux, and Windows. A stock binary is enough
  for the normal demo; the custom Fly View overlay requires a custom build.
- Mission Planner is Windows-only. Install the thin plugin once with
  `examples/mission-planner-plugin/Install-UtmConnectorPlugin.ps1`, then
  restart Mission Planner.

## Presentation startup

Use the full Flight Blender + ArduPilot demo when the simulator environment is
already prepared:

```sh
uv run python scripts/openutm_demo.py --gcs auto
```

For a custom QGroundControl build:

```sh
export QGROUNDCONTROL_COMMAND="/path/to/Custom-QGroundControl"
make gcs-custom-qgc-demo
```

The launcher starts Flight Blender, the connector, and SITL, opens the browser
operator console, and connects the detected GCS. Use `make demo` instead for a
clean browser-only demo with no Docker or simulator.

Before the presentation, run the disposable verification once:

```sh
make gcs-demo-verify
# or, for the one-link physical-aircraft topology:
make gcs-router-demo-verify
```

Both commands exercise the connector lifecycle, confirm a vehicle heartbeat
at the GCS endpoint, and clean up the services they started.

## What to show

1. In the GCS, show the vehicle connected and leave all flight-control
   authority there.
2. In the UTM Operator Console, choose the detected vehicle and click
   **Sample route**. The console shows the route and live telemetry.
3. Click **Validate & save**, then **Submit to UTM**.
4. Click **Start operation**. Wait for the operation card to show
   **ACTIVE / CONFORMING** while the telemetry position changes.
5. Point out the readiness strip, route map, telemetry quality, conformance
   state, and audit trail. These are the UTM additions; arming, flight modes,
   and mission execution remain in the GCS.
6. Click **Complete** and show the terminal **COMPLETED** state.

For a more realistic GCS-led flow, export a QGroundControl `.plan` or Mission
Planner `.waypoints` file and use **Open mission file** instead of **Sample
route**. The connector normalizes both formats into the same mission model.

## Real-drone topology

Do not open the same physical serial/radio link independently from two
applications. Use one companion-computer MAVLink router:

```text
vehicle radio/serial link -> MAVLink Router
                              -> GCS output (UDP 14550)
                              -> connector output (UDP 14551)
```

The GCS remains the only flight-control authority. The connector consumes
telemetry and performs explicit read-only onboard-mission checks; it does not
arm, take off, change modes, or upload a vehicle mission.

Validate the checked-in topology with:

```sh
make gcs-router-demo-check
```

On macOS and Windows the supervised demo can run the router in Docker. On a
real aircraft, install `mavlink-routerd` on the companion computer and point
the connector at its UDP output rather than opening the serial device twice.

## Mission Planner flow on Windows

From PowerShell, with Mission Planner closed:

```powershell
.\examples\mission-planner-plugin\Install-UtmConnectorPlugin.ps1
```

Start the connector/demo, restart Mission Planner, and use its **UTM
Connector** toolbar menu. **Sync current mission** reads the mission visible
in Flight Planner and sends it to the connector. Submit/start/refresh/cancel/
complete actions stay beside the normal GCS workflow; the browser console is
still the detailed conformance view.

## Stop and recover

Press `Ctrl+C` in the terminal that started the supervised demo. It cleans up
the connector, simulator, and only the Flight Blender/router containers owned
by that run. If a presentation was interrupted, confirm cleanup with:

```sh
docker ps
```

Then rerun `make demo-check`. If port 14550, 14551, 8000, or 8001 is already
occupied, either stop the old process or start the demo with alternate GCS and
connector UDP ports as described in `docs/local-development.md`.
