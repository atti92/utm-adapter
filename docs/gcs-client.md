# Thin GCS client boundary

`utm_connector.gcs_client.ConnectorClient` is the portable client boundary for
Mission Planner, QGroundControl, or another GCS adapter. It only speaks to the
local connector API; it does not know about Flight Blender, provider schemas,
MAVLink dialects, or vehicle-control commands.

Mission Planner itself remains a Windows-specific host application. The
optional thin plugin in
[`examples/mission-planner-plugin/`](../examples/mission-planner-plugin/)
maps its normal Flight Data menu to this client boundary while keeping
provider-specific behavior in the connector process.
The same client contract can be implemented by a C#, QML, or other host-side
adapter without changing the connector API.

Example:

```python
from datetime import datetime, timedelta, timezone

from utm_connector.gcs_client import ConnectorClient

with ConnectorClient("http://127.0.0.1:8000", correlation_id="<session-uuid>") as connector:
    diagnostics = connector.metrics()
    vehicles = connector.vehicles()
    vehicle_id = vehicles[0]["vehicle_id"]
    connector.upload_qgroundcontrol_plan(
        vehicle_id,
        plan,
        valid_from=datetime.now(timezone.utc) + timedelta(minutes=1),
        valid_until=datetime.now(timezone.utc) + timedelta(minutes=31),
    )
    connector.refresh_onboard_mission(vehicle_id)
    onboard = connector.onboard_mission(vehicle_id)
    raw = connector.raw_onboard_mission(vehicle_id)
    connector.import_onboard_mission(
        vehicle_id,
        valid_from=datetime.now(timezone.utc) + timedelta(minutes=1),
        valid_until=datetime.now(timezone.utc) + timedelta(minutes=31),
    )
```

`refresh_onboard_mission()` only requests a read-only MAVLink mission
download; it does not upload, alter, arm, or control the vehicle. The
subsequent `onboard_mission()` call returns the connector's latest stored
snapshot, which lets a GCS show mission drift consistently across
QGroundControl and Mission Planner adapters. A vehicle that has not reported a
mission yet returns HTTP 404. `raw_onboard_mission()` exposes the route before
UTM-only metadata is applied. `import_onboard_mission()` promotes that route to
the normal mission workflow, but requires the host GCS to provide the validity
window and corridor radius explicitly; the connector never infers them from
MAVLink.

`metrics()` returns process-local diagnostics suitable for a compact GCS
status panel: uptime, active vehicles and operations, telemetry publication
counters, provider request latency/error counters, and additive per-vehicle
health/drift plus active operation state details.

Connector responses include an `X-Correlation-ID` header. Send a UUID with the
same header when a host GCS starts an operator action to make support logs
traceable across the request boundary.

The client intentionally returns JSON dictionaries so the host GCS can map
connector state into its own native UI models. Use
[qgcs-config/connector-manifest.json](../qgcs-config/connector-manifest.json)
for endpoint discovery and compatibility checks.
