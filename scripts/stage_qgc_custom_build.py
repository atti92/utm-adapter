"""Stage the UTM QGroundControl overlay into an isolated custom build directory.

The generated directory is deliberately separate from QGroundControl's
``custom-example`` tree.  This makes the setup repeatable and prevents an
operator from accidentally overwriting an existing QGC customization.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "examples" / "qgroundcontrol-custom-build"
MARKER_NAME = ".utm-connector-overlay.json"


class StageError(RuntimeError):
    """Raised when staging would be unsafe or incomplete."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qgc-source",
        type=Path,
        default=Path(os.environ.get("QGC_SOURCE_DIR", ROOT.parent / "qgroundcontrol")),
        help="QGroundControl checkout (default: QGC_SOURCE_DIR or ../qgroundcontrol)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="generated custom directory (default: <qgc-source>/custom-utm-connector)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing generated directory after moving it to a backup",
    )
    return parser


def _backup_path(output: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = output.with_name(f"{output.name}.backup-{stamp}")
    suffix = 1
    while candidate.exists():
        candidate = output.with_name(f"{output.name}.backup-{stamp}-{suffix}")
        suffix += 1
    return candidate


def stage_custom_build(qgc_source: Path, output: Path, *, force: bool = False) -> Path:
    """Copy QGC's custom example and replace only its Fly View layer.

    QGC's sample custom build is intentionally single-stack and disables the
    ArduPilot factory.  The connector is meant to sit alongside existing GCS
    users, so keep the sample's PX4 customization while restoring the stock
    ArduPilot factory in the generated build.
    """

    qgc_source = qgc_source.expanduser().resolve()
    output = output.expanduser().resolve()
    upstream_example = qgc_source / "custom-example"
    upstream_layer = upstream_example / "src" / "FlyViewCustomLayer.qml"
    connector_layer = OVERLAY / "src" / "FlyViewCustomLayer.qml"
    connector_bridge_header = OVERLAY / "src" / "UtmConnectorBridge.h"
    connector_bridge_source = OVERLAY / "src" / "UtmConnectorBridge.cc"

    if not upstream_example.is_dir():
        raise StageError(f"QGroundControl custom-example directory not found: {upstream_example}")
    if not upstream_layer.is_file():
        raise StageError(f"QGroundControl Fly View layer not found: {upstream_layer}")
    if not connector_layer.is_file():
        raise StageError(f"UTM connector overlay not found: {connector_layer}")
    for bridge_file in (connector_bridge_header, connector_bridge_source):
        if not bridge_file.is_file():
            raise StageError(f"UTM connector QGC bridge not found: {bridge_file}")
    try:
        output.relative_to(qgc_source)
    except ValueError as exc:
        raise StageError(
            "output must be inside the QGroundControl checkout so QGC_CUSTOM_DIR "
            "can refer to it"
        ) from exc
    if output == qgc_source or output == upstream_example or upstream_example in output.parents:
        raise StageError("output must not be the QGroundControl custom-example tree")

    if output.exists():
        marker = output / MARKER_NAME
        if not force:
            raise StageError(
                f"output already exists: {output}; choose another path or use --force"
            )
        if not marker.is_file():
            raise StageError(
                f"refusing to replace an unmarked directory: {output}; remove it manually "
                "or choose another path"
            )
        backup = _backup_path(output)
        shutil.move(str(output), str(backup))

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(upstream_example, output)
    shutil.copy2(connector_layer, output / "src" / "FlyViewCustomLayer.qml")
    shutil.copy2(connector_bridge_header, output / "src" / "UtmConnectorBridge.h")
    shutil.copy2(connector_bridge_source, output / "src" / "UtmConnectorBridge.cc")

    custom_cmake = output / "CMakeLists.txt"
    custom_plugin_header = output / "src" / "CustomPlugin.h"
    custom_plugin_source = output / "src" / "CustomPlugin.cc"
    if custom_cmake.is_file() and custom_plugin_header.is_file() and custom_plugin_source.is_file():
        cmake_text = custom_cmake.read_text(encoding="utf-8")
        source_anchor = "    ${CMAKE_CURRENT_SOURCE_DIR}/src/MissionManager/PerimeterScanPlanCreator.h\n"
        if source_anchor not in cmake_text:
            raise StageError("QGC custom template no longer exposes the expected custom source list")
        cmake_text = cmake_text.replace(
            source_anchor,
            source_anchor
            + "    ${CMAKE_CURRENT_SOURCE_DIR}/src/UtmConnectorBridge.cc\n"
            + "    ${CMAKE_CURRENT_SOURCE_DIR}/src/UtmConnectorBridge.h\n",
            1,
        )
        custom_cmake.write_text(cmake_text, encoding="utf-8")

        plugin_header = custom_plugin_header.read_text(encoding="utf-8")
        plugin_header_anchor = '#include "QGCCorePlugin.h"\n'
        if plugin_header_anchor not in plugin_header:
            raise StageError("QGC custom plugin header no longer has its expected include section")
        plugin_header = plugin_header.replace(
            plugin_header_anchor,
            plugin_header_anchor + '#include "UtmConnectorBridge.h"\n',
            1,
        )
        plugin_class_anchor = "class CustomPlugin : public QGCCorePlugin\n{\n    Q_OBJECT\n"
        if plugin_class_anchor not in plugin_header:
            raise StageError("QGC custom plugin header no longer has its expected class declaration")
        plugin_header = plugin_header.replace(
            plugin_class_anchor,
            plugin_class_anchor
            + "    Q_PROPERTY(UtmConnectorBridge* utmConnector READ utmConnector CONSTANT)\n",
            1,
        )
        plugin_getter_anchor = "    static QGCCorePlugin *instance();\n"
        if plugin_getter_anchor not in plugin_header:
            raise StageError("QGC custom plugin header no longer exposes its instance declaration")
        plugin_header = plugin_header.replace(
            plugin_getter_anchor,
            plugin_getter_anchor
            + "    UtmConnectorBridge *utmConnector() const { return _utmConnector; }\n",
            1,
        )
        plugin_member_anchor = "    CustomOptions *_options = nullptr;\n"
        if plugin_member_anchor not in plugin_header:
            raise StageError("QGC custom plugin header no longer exposes its options member")
        plugin_header = plugin_header.replace(
            plugin_member_anchor,
            plugin_member_anchor + "    UtmConnectorBridge *_utmConnector = nullptr;\n",
            1,
        )
        custom_plugin_header.write_text(plugin_header, encoding="utf-8")

        plugin_source = custom_plugin_source.read_text(encoding="utf-8")
        constructor_anchor = "    , _options(new CustomOptions(this, this))\n"
        if constructor_anchor not in plugin_source:
            raise StageError("QGC custom plugin source no longer has its expected constructor")
        plugin_source = plugin_source.replace(
            constructor_anchor,
            constructor_anchor + "    , _utmConnector(new UtmConnectorBridge(this))\n",
            1,
        )
        custom_plugin_source.write_text(plugin_source, encoding="utf-8")

    overrides = output / "cmake" / "CustomOverrides.cmake"
    if not overrides.is_file():
        raise StageError(f"QGroundControl custom override file not found: {overrides}")
    overrides_text = overrides.read_text(encoding="utf-8")
    disabled_apm = 'set(QGC_DISABLE_APM_PLUGIN_FACTORY ON CACHE BOOL "Disable APM Plugin Factory" FORCE)'
    enabled_apm = 'set(QGC_DISABLE_APM_PLUGIN_FACTORY OFF CACHE BOOL "Disable APM Plugin Factory" FORCE)'
    if disabled_apm not in overrides_text:
        raise StageError(
            "QGroundControl custom template no longer contains its expected "
            "ArduPilot factory override; inspect it before staging"
        )
    overrides.write_text(overrides_text.replace(disabled_apm, enabled_apm, 1), encoding="utf-8")

    marker_payload = {
        "kind": "utm-connector-qgroundcontrol-custom-build",
        "source": str(qgc_source),
        "overlay": str(OVERLAY),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "custom_dir": output.name,
        "standard_ardupilot_factory": True,
        "native_utm_actions": True,
    }
    (output / MARKER_NAME).write_text(
        json.dumps(marker_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def _print_next_steps(qgc_source: Path, output: Path) -> None:
    build_dir = qgc_source / "build" / "utm-connector"
    custom_dir = output.relative_to(qgc_source).as_posix()
    print(f"[ok] staged UTM QGroundControl custom build: {output}")
    print()
    print("Build it from the QGroundControl checkout:")
    print(f"  cmake -S {qgc_source} -B {build_dir} -DQGC_CUSTOM_DIR={custom_dir}")
    print(f"  cmake --build {build_dir} --parallel")
    print()
    print("The stock QGroundControl binary remains unchanged; the generated build")
    print("contains the native UTM status and action card, plus the operator console link.")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    qgc_source = args.qgc_source.expanduser().resolve()
    output = (args.output or qgc_source / "custom-utm-connector").expanduser().resolve()
    try:
        staged = stage_custom_build(qgc_source, output, force=args.force)
    except (OSError, StageError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    _print_next_steps(qgc_source, staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
