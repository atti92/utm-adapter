"""Validate the UTM connector's QGroundControl custom-build integration.

This is intentionally a source/configuration check. Building QGroundControl
still requires the platform's native Qt and compiler toolchain.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "examples" / "qgroundcontrol-custom-build"


def _git_revision(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "describe", "--tags", "--exact-match", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def validate(qgc_root: Path, expected_tag: str) -> list[str]:
    checks = {
        "QGroundControl source tree": qgc_root / "src" / "FlyView" / "FlyViewCustomLayer.qml",
        "QGC custom build template": qgc_root / "custom-example" / "CMakeLists.txt",
        "QGC resource override example": qgc_root / "custom-example" / "custom.qrc",
        "QGC override interceptor": qgc_root / "custom-example" / "src" / "CustomPlugin.cc",
        "connector overlay": OVERLAY / "src" / "FlyViewCustomLayer.qml",
        "connector overlay resource": OVERLAY / "utm_connector.qrc",
        "connector CMake fragment": OVERLAY / "CMakeLists.fragment.cmake",
    }
    errors: list[str] = []
    for label, path in checks.items():
        if not path.is_file():
            errors.append(f"{label} missing: {path}")

    if errors:
        return errors

    qgc_layer = checks["QGroundControl source tree"].read_text()
    qgc_qrc = checks["QGC resource override example"].read_text()
    qgc_plugin = checks["QGC override interceptor"].read_text()
    connector_qrc = checks["connector overlay resource"].read_text()
    fragment = checks["connector CMake fragment"].read_text()
    overlay = checks["connector overlay"].read_text()

    expectations = (
        ("QGC loads FlyViewCustomLayer", "FlyViewCustomLayer" in qgc_layer),
        ("QGC documents the /Custom resource prefix", 'prefix="/Custom/qml"' in qgc_qrc),
        ("QGC custom build installs a URL interceptor", "addUrlInterceptor" in qgc_plugin),
        ("QGC interceptor maps /qml resources", 'QStringLiteral(":/Custom%1")' in qgc_plugin),
        (
            "connector QRC uses the official alias",
            'alias="QGroundControl/FlyView/FlyViewCustomLayer.qml"' in connector_qrc,
        ),
        ("connector QRC uses the /Custom prefix", 'prefix="/Custom/qml"' in connector_qrc),
        ("fragment registers CUSTOM_RESOURCES", "CUSTOM_RESOURCES" in fragment),
        ("overlay imports the Fly View module", "QGroundControl.FlyView" in overlay),
        ("overlay stays non-commanding", "COMMAND_LONG" not in overlay and "sendMavlink" not in overlay),
    )
    for label, passed in expectations:
        if not passed:
            errors.append(f"{label} check failed")

    revision = _git_revision(qgc_root)
    if expected_tag and revision != expected_tag:
        errors.append(
            f"QGroundControl checkout is {revision or 'not an exact tag'}; expected {expected_tag}"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qgc-source",
        type=Path,
        default=Path(os.environ.get("QGC_SOURCE_DIR", ROOT.parent / "qgroundcontrol")),
        help="QGroundControl checkout (default: QGC_SOURCE_DIR or ../qgroundcontrol)",
    )
    parser.add_argument(
        "--expected-tag",
        default="v5.1.4",
        help="exact QGroundControl tag to validate (default: v5.1.4)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when the QGroundControl checkout is not available",
    )
    args = parser.parse_args()
    qgc_root = args.qgc_source.expanduser().resolve()

    if not qgc_root.is_dir():
        message = f"QGroundControl source not found at {qgc_root}"
        if args.strict:
            print(f"[error] {message}")
            return 1
        print(f"[skip] {message}; install/clone it to validate the native overlay")
        return 0

    errors = validate(qgc_root, args.expected_tag)
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 1

    print(f"[ok] QGroundControl {args.expected_tag} custom overlay contract is valid")
    print(f"[ok] source: {qgc_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
