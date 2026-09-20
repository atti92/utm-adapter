import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts import check_connector_manifest
from utm_connector.integration import integration_manifest


def test_manifest_check_accepts_checked_in_contract() -> None:
    assert check_connector_manifest.validate() == []


def test_manifest_check_reports_contract_drift(tmp_path) -> None:
    manifest_path = tmp_path / "connector-manifest.json"
    manifest = integration_manifest()
    manifest["mavlink"]["vehicle_control"] = "commanding"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = check_connector_manifest.validate(manifest_path)

    assert len(errors) == 1
    assert "differs from the live integration contract" in errors[0]


def test_manifest_check_reports_invalid_json(tmp_path) -> None:
    manifest_path = tmp_path / "connector-manifest.json"
    manifest_path.write_text("{not-json", encoding="utf-8")

    errors = check_connector_manifest.validate(manifest_path)

    assert errors == [f"manifest is not valid JSON: {manifest_path} (Expecting property name enclosed in double quotes)"]
