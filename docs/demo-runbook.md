# UTM connector demo runbook

This is the shortest repeatable path for a presentation. The browser console
handles the UTM workflow; QGroundControl or Mission Planner remains the normal
vehicle-control application.

## One-time preparation

From the repository root:

```sh
uv run python scripts/setup_demo.py
uv run python scripts/check_demo.py --gcs qgroundcontrol
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
uv run python scripts/openutm_demo.py --gcs qgroundcontrol
```

For a custom QGroundControl build:

```sh
export QGROUNDCONTROL_COMMAND="/path/to/Custom-QGroundControl"
make gcs-custom-qgc-demo
```

Close QGroundControl before starting the launcher so a second instance does
not exit with an “already running” error. Keep this terminal open. On this Mac,
run the commands from `/Users/atti/repos/utm-adapter`.

The launcher starts Flight Blender, the connector, and SITL, opens the browser
operator console, and connects the detected GCS. Use `make demo` instead for a
clean browser-only demo with no Docker or simulator.

Each supervised run also writes ready-to-open mission files under
`.local/openutm-demo/`: `mission-qgroundcontrol.plan` for QGroundControl,
`mission-planner.waypoints` for Mission Planner, and `mission.json` for the
connector API. In the GCS, open the corresponding file from its normal mission
file picker, then use **Open mission file** in the operator console. The
standard GCS files carry route geometry; enter or review the UTM validity window
and corridor in the console before saving.

## Rehearse both formats on this Mac

With the supervised demo still running, open a second terminal in the same
repository and run these **one at a time**:

```sh
uv run python scripts/verify_running_demo.py --mission-format qgroundcontrol
uv run python scripts/verify_running_demo.py --mission-format mission-planner
```

Each waits for GOOD telemetry and a 3D GPS fix, creates a fresh operation,
validates/imports the specified GCS format,
submits and starts it, waits through its 15-second lead time, requires
**two new acknowledged provider publications plus ACTIVE / CONFORMING**,
and completes it with publication STOPPED. Expect about 17 seconds per run.
A failed run attempts to cancel its operation. Use a dedicated demo connector
with no other active operations; the publication counter belongs to the whole
connector. These checks replace the saved mission, so run them before the
manual presentation and import your chosen file again afterward.

For a disposable rehearsal that starts and cleans up its own stack instead:

```sh
make gcs-demo-verify
make integration-mission-planner-mission-verify
```

Stop the existing supervised demo before using those commands; they need the
same ports. Likewise `check_demo.py` is a **before-start** check and reports
port 8001 occupied while the demo is running. Do not launch both GCS programs
on UDP 14550 at once.

## Live presentation: QGroundControl on this Mac

1. Start the supervised demo using the command above. Open
   `http://127.0.0.1:8001/ui/` if the browser did not open. Confirm the readiness
   strip says **Flight Blender reachable** and **1 vehicle online**.
2. In QGroundControl, show the connected vehicle near Budapest. Leave SITL
   disarmed. Open **Plan** view and use its mission **File / Open** action to
   load `.local/openutm-demo/mission-qgroundcontrol.plan`. The native file
   picker shortcut `Cmd+Shift+G` accepts the full path. Menu wording can vary
   by QGC version. This native file-picker step remains a manual rehearsal
   check: desktop automation could observe QGC telemetry but could not operate
   its Qt controls on this Mac.
3. In the browser choose **Open operator workspace**, select **sitl-1**, then
   **Open mission file** and select that same `.plan` file. It should show a
   **2 waypoint route**. Stock QGC uses the browser for UTM actions; the native
   Fly View UTM overlay requires a separate custom QGC build.
4. Review the validity window and corridor. The console uses local time
   (Budapest on this Mac), converts it to UTC, and defaults the start a few
   minutes ahead. If the start has passed, choose **Sample route** to reset
   the window, then reopen the desired file. Set the corridor to **200 m** for
   the ground demonstration, then **Validate & save** and **Submit to UTM**.
5. Confirm **ACCEPTED / AUTHORIZED**, click **Start operation**, and wait until
   the displayed validity start. Publication is withheld before that time;
   local CONFORMING alone does not prove publication. Once the window opens,
   show **ACTIVE / CONFORMING** and **TELEMETRY_PUBLISHED** in the audit trail.
6. Show the GCS beside the console: both consume the same simulated vehicle.
   Position stays still because SITL is disarmed. Fresh event timestamps and
   increasing `telemetry.published_total` at `/v1/metrics` demonstrate the live
   stream. This rehearsal does not arm, take off, or execute the mission.
7. Click **Complete**; confirm **COMPLETED / STOPPED**. Reopen a mission and
   review a future validity window before repeating. Generated files are
   refreshed on launcher startup; avoid using an old canonical file whose
   embedded times have expired.

Repeat steps 3–7 with `mission-planner.waypoints` to demonstrate Mission
Planner interchange on the Mac. It shows **3 waypoint route** because the
connector includes Mission Planner's planned home record plus its two mission
commands. Mission Planner's native grid removes the home row and shows the
two actual commands. This file import is available without the Windows app.

See [the recorded rehearsal results](demo-validation.md) for the tested scope
and remaining native desktop checks.

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
For a Linux companion, the repository includes a reviewable service unit at
[`examples/mavlink-router/mavlink-router.service.example`](../examples/mavlink-router/mavlink-router.service.example);
install it only after reviewing the generated UART config and the binary path.

## Mission Planner flow on Windows

**Prepared instructions; native execution has not been tested here.** The Mac
interchange test does not validate C# compilation, plugin menu loading, the
native file picker, or a Windows MAVLink connection.

Use a Windows machine with Git, uv, Docker Desktop running Linux containers,
and Mission Planner installed. Copy this repository including the demo changes.
Run PowerShell in the repository root. Use the Docker PX4 option to avoid
requiring a native Windows ArduPilot build:

```powershell
uv run python scripts/setup_demo.py --simulator px4
.\examples\mission-planner-plugin\Install-UtmConnectorPlugin.ps1
uv run python scripts/openutm_demo.py --simulator px4 --gcs mission-planner --check
uv run python scripts/openutm_demo.py --simulator px4 --gcs mission-planner
```

Close Mission Planner before the installer/launcher. If installed under
Program Files, the installer may need an elevated PowerShell; for a portable
install pass `-MissionPlannerRoot 'D:\Apps\Mission Planner'`. The installer
refuses to replace an existing plugin unless `-Force` is given and saves a
backup when replacing it.

With that terminal left running:

1. In Mission Planner select **UDP**, click **Connect**, and listen on **14550**.
   Confirm the live vehicle link. If a firewall prompt appears, allow the demo
   only on the network profile you intend to use.
2. In **Flight PLAN**, use **Load WP File** (or the map's **Load WP File**
   context-menu action) and select
   `.local\openutm-demo\mission-planner.waypoints`. Confirm home plus two
   route commands, with absolute/AMSL altitude. If asked to reset planned home
   to the loaded coordinates, accept for this local simulation.
3. In **UTM Connector → Configure connector...**, explicitly set connector URL
   `http://127.0.0.1:8001` and vehicle ID `sitl-1`.
4. Choose **Sync current mission**, **Submit operation**, then **Start
   operation**. Sync supplies a 15-second lead time. Choose **Refresh operation
   status** after that window opens; expect ACTIVE / CONFORMING. Use **Open
   operator console** for the detailed audit trail and live metrics.
5. Choose **Complete operation** (the Complete action in the plugin menu),
   then refresh to confirm COMPLETED / STOPPED. No vehicle upload or flight
   execution is needed for this ground demonstration.

In a second PowerShell terminal, confirm the installation and connected vehicle:

```powershell
.\examples\mission-planner-plugin\Test-UtmConnectorPlugin.ps1 `
  -ConnectorUrl 'http://127.0.0.1:8001' -VehicleId 'sitl-1'
```

Run the two `verify_running_demo.py` commands above before the manual flow to
repeat both interchange checks against this Windows stack. If the plugin menu
does not appear, use browser **Open mission file** for the demo and record the
native plugin failure separately. Optional source/compile validation is
explained in `examples/mission-planner-plugin/README.md`; a source contract
check alone is insufficient to declare the Windows plugin tested.

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
