# Mission Planner integration

This directory contains a thin, non-commanding Mission Planner plugin. It
adds a `UTM Connector` entry to the normal Flight Data menu so an operator can
open the connector console and check that the local connector is online without
leaving the GCS workflow.

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

The plugin assumes the default connector address `http://127.0.0.1:8000`. If
the connector runs on another host or port, change `ConnectorBaseUrl` in the
source before copying it.

## Operator flow

Mission Planner remains the familiar vehicle-facing GCS. Use the connector web
console for the UTM-specific steps:

1. Confirm the vehicle appears and the telemetry readiness indicator is good.
2. Load a Mission Planner `.waypoints` file in the connector console, or use a
   QGroundControl `.plan` file.
3. Validate and save the declaration, submit it to the configured UTM provider,
   then start the operation when its validity window opens.
4. Watch authorization, conformance, and telemetry state in the same console.

This source file is intentionally kept compatible with Mission Planner's
script-plugin model and uses only the .NET Framework APIs normally available to
the host. This repository does not include a Windows Mission Planner runtime,
so final plugin compilation and menu verification must be performed on a
Windows test machine with Mission Planner installed.
