import json
from pathlib import Path

from utm_connector.integration import integration_manifest


ROOT = Path(__file__).parents[1]


def test_checked_in_connector_manifest_matches_live_contract_shape() -> None:
    manifest = json.loads((ROOT / "qgcs-config" / "connector-manifest.json").read_text())

    assert manifest == integration_manifest()
    assert manifest["schema_version"] == "1.0"
    assert manifest["operator_console"]["path"] == "/ui/"
    assert manifest["api"]["discovery_path"] == "/v1/integration"
    assert manifest["api"]["mission"]["qgroundcontrol"] == {
        "method": "PUT",
        "path": "/v1/missions/{vehicle_id}/qgroundcontrol",
    }
    assert manifest["api"]["mission"]["mission_planner"] == {
        "method": "PUT",
        "path": "/v1/missions/{vehicle_id}/mission-planner",
    }
    assert manifest["mavlink"]["vehicle_control"] == "none"


def test_product_metadata_remains_valid_json() -> None:
    product = json.loads((ROOT / "qgcs-config" / "product.json").read_text())

    assert isinstance(product["available_services"], list)
