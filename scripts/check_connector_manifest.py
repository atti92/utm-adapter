"""Validate the checked-in GCS manifest against the live connector contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utm_connector.integration import integration_manifest


DEFAULT_MANIFEST = ROOT / "qgcs-config" / "connector-manifest.json"


def validate(manifest_path: Path = DEFAULT_MANIFEST) -> list[str]:
    """Return actionable errors when a shipped manifest drifts from runtime."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"manifest not found: {manifest_path}"]
    except json.JSONDecodeError as exc:
        return [f"manifest is not valid JSON: {manifest_path} ({exc.msg})"]

    if manifest != integration_manifest():
        return [
            "checked-in GCS manifest differs from the live integration contract: "
            f"{manifest_path}; update it from utm_connector.integration.integration_manifest()"
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="checked-in connector manifest (default: qgcs-config/connector-manifest.json)",
    )
    args = parser.parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    errors = validate(manifest_path)
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 1

    print(f"[ok] GCS connector manifest matches the live contract: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
