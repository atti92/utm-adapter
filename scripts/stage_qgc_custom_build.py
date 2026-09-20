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
    """Copy QGC's custom example and replace only its Fly View layer."""

    qgc_source = qgc_source.expanduser().resolve()
    output = output.expanduser().resolve()
    upstream_example = qgc_source / "custom-example"
    upstream_layer = upstream_example / "src" / "FlyViewCustomLayer.qml"
    connector_layer = OVERLAY / "src" / "FlyViewCustomLayer.qml"

    if not upstream_example.is_dir():
        raise StageError(f"QGroundControl custom-example directory not found: {upstream_example}")
    if not upstream_layer.is_file():
        raise StageError(f"QGroundControl Fly View layer not found: {upstream_layer}")
    if not connector_layer.is_file():
        raise StageError(f"UTM connector overlay not found: {connector_layer}")
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

    marker_payload = {
        "kind": "utm-connector-qgroundcontrol-custom-build",
        "source": str(qgc_source),
        "overlay": str(OVERLAY),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "custom_dir": output.name,
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
    print("contains the read-only UTM status card and opens the operator console.")


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
