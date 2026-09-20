# Mission Planner integration

This directory contains a thin, non-commanding Mission Planner plugin. It
adds a `UTM Connector` entry to the normal Flight Data menu so an operator can
configure the local connector, sync the mission currently shown in Mission
Planner, and drive the UTM operation lifecycle without leaving the GCS
workflow.

The plugin does not replace Mission Planner's vehicle-control or mission-editing
features, and it never writes to the vehicle MAVLink connection. The connector
continues to consume the vehicle stream through the configured MAVLink router
and handles UTM declaration, conformance, and telemetry publication in its own
operator console.

## Install

1. Start the connector locally. From the repository root, `make demo` is the
   quickest self-contained option; for a real vehicle use the configuration in
   [`docs/local-development.md`](../../docs/local-development.md).
2. Copy [`UtmConnectorPlugin.cs`](UtmConnectorPlugin.cs) into Mission Planner's
   `plugins` directory.
3. Restart Mission Planner. Its plugin loader compiles C# source files from
   that directory when Mission Planner starts.
4. In Flight Data, open `UTM Connector` and choose `Open operator console`.

The plugin starts with connector address `http://127.0.0.1:8000` and vehicle ID
`sitl-1`. For the full Flight Blender demo it automatically falls back to
`http://127.0.0.1:8001` when the standalone port is not serving a connector, so
the normal demo does not require a port edit. Use `Configure connector...` from
the menu to change either value; the values are persisted in Mission Planner
settings.

## Operator flow

Mission Planner remains the familiar vehicle-facing GCS. The plugin exposes
the common UTM steps directly from its menu:

1. Configure the connector URL and the connector vehicle ID once.
2. Load or edit the mission in Mission Planner's Flight Planner view.
3. Choose `Sync current mission`. The plugin gives the declaration a 15-second
   lead time so the local demo can be started without a one-minute wait.
4. Choose `Submit operation`, then `Start operation` when ready. `Cancel` and
   `Complete` are available for the same operation. Use `Refresh operation
   status` to pull the latest declaration, authorization, telemetry, and
   conformance state from the connector.
5. Open the operator console when you want the richer authorization,
   conformance, and telemetry view.

The connector currently accepts navigable `WAYPOINT` and `TAKEOFF` items for
this direct workflow. Unsupported Mission Planner actions are rejected with a
clear message instead of being silently dropped; they can still be handled by
the existing file-import path after the mission is reduced to a supported
route.

This source file is intentionally kept compatible with Mission Planner's
script-plugin model and uses only the .NET Framework APIs normally available to
the host. This repository does not include a Windows Mission Planner runtime,
so final plugin compilation and menu verification must be performed on a
Windows test machine with Mission Planner installed.
