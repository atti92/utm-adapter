# UTM Connector standalone package

This archive contains a self-contained UTM Connector executable for Linux or
Windows, a configuration example, and this quick start.

1. Extract the archive and copy `utm-connector.example.json` to
   `utm-connector.json` in the same directory.
2. Edit the provider URL, active GCS adapters, and MAVLink connection details.
   The example targets Flight Blender at `http://127.0.0.1:8989` and listens
   for a router output on UDP port 14551.
3. Set provider credentials in the process environment. For a bearer token,
   set `UTM_CONNECTOR_FLIGHT_BLENDER_BEARER_TOKEN`; do not commit real
   credentials to the JSON file.
4. Run `utm-connector` (`utm-connector.exe` on Windows). Pass
   `--config PATH` to load a config file from another location. Use
   `--open-browser` to open the local operator console automatically.

Open `http://127.0.0.1:8000/` to view provider reachability, MAVLink status,
connector version, and supported GCS integrations. The full mission and
operation workflow is under **Open operator workspace**. QGroundControl and
Mission Planner remain in control of the aircraft; this connector reads
MAVLink and does not send vehicle-control commands.

`utm-connector --version` prints the build version. The archive name includes
the version, OS, and CPU architecture. Verify the archive against the
matching `.sha256` release asset before running it.
