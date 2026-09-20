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

with ConnectorClient("http://127.0.0.1:8000") as connector:
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
```

`refresh_onboard_mission()` only requests a read-only MAVLink mission
download; it does not upload, alter, arm, or control the vehicle. The
subsequent `onboard_mission()` call returns the connector's latest stored
snapshot, which lets a GCS show mission drift consistently across
QGroundControl and Mission Planner adapters. A vehicle that has not reported a
mission yet returns HTTP 404.

The client intentionally returns JSON dictionaries so the host GCS can map
connector state into its own native UI models. Use
[qgcs-config/connector-manifest.json](../qgcs-config/connector-manifest.json)
for endpoint discovery and compatibility checks.
