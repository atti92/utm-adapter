"""Machine-readable contract for thin GCS integrations.

The contract deliberately describes the connector boundary rather than a
QGroundControl-specific plugin API. A stock GCS can continue to create and
export a ``.plan`` file, while a small adapter or operator console discovers
the connector endpoints from ``/v1/integration``.
"""

from copy import deepcopy

from .missions import NAVIGABLE_MISSION_COMMANDS_INFO


INTEGRATION_MANIFEST = {
    "schema_version": "1.0",
    "connector": {
        "name": "utm-operations-connector",
        "role": "local_utm_adapter",
    },
    "operator_console": {
        "path": "/ui/",
        "launch_url": "/ui/",
        "entrypoint": "browser",
    },
    "api": {
        "prefix": "/v1",
        "discovery_path": "/v1/integration",
        "capabilities_path": "/v1/capabilities",
        "health_path": "/v1/health",
        "metrics_path": "/v1/metrics",
        "vehicles_path": "/v1/vehicles",
        "telemetry_path": "/v1/vehicles/{vehicle_id}",
        "vehicle_status_path": "/v1/vehicles/{vehicle_id}/status",
        "mission": {
            "canonical": {
                "method": "PUT",
                "path": "/v1/missions/{vehicle_id}",
            },
            "qgroundcontrol": {
                "method": "PUT",
                "path": "/v1/missions/{vehicle_id}/qgroundcontrol",
            },
            "mission_planner": {
                "method": "PUT",
                "path": "/v1/missions/{vehicle_id}/mission-planner",
            },
            "onboard": {
                "method": "GET",
                "path": "/v1/vehicles/{vehicle_id}/onboard-mission",
            },
            "onboard_refresh": {
                "method": "POST",
                "path": "/v1/vehicles/{vehicle_id}/onboard-mission/refresh",
            },
        },
        "operations": {
            "intent": {
                "method": "POST",
                "path": "/v1/operator-intents?vehicle_id={vehicle_id}",
            },
            "get": {
                "method": "GET",
                "path": "/v1/operations/{operation_id}",
            },
            "refresh": {
                "method": "POST",
                "path": "/v1/operations/{operation_id}/refresh",
            },
        },
    },
    "mission_formats": ["canonical", "qgroundcontrol", "mission-planner"],
    "mission_commands": list(NAVIGABLE_MISSION_COMMANDS_INFO),
    "recording": {
        "configuration": "UTM_CONNECTOR_RECORD_PATH",
        "raw_mavlink_record_type": "mavlink_frame",
        "replay": "JsonlReplay.replay_mavlink",
    },
    "mavlink": {
        "vehicle_control": "none",
        "mission_download": True,
        "recommended_topology": "single_router_endpoint",
        "connector_input_uri": "udpin:127.0.0.1:14551",
    },
}


def integration_manifest() -> dict:
    """Return a defensive copy so callers cannot mutate the shared contract."""

    return deepcopy(INTEGRATION_MANIFEST)
