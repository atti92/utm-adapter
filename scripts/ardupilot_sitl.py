"""Launch a built ArduPilot SITL vehicle for local connector testing.

This helper deliberately starts only the simulator. The GCS and connector
remain independently visible and stoppable processes, which makes it useful
for both demos and integration tests.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Sequence


DEFAULT_HOME = "47.4979,19.0402,137,0"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a built ArduCopter SITL binary with GCS and connector outputs"
    )
    parser.add_argument(
        "--ardupilot-root",
        type=Path,
        default=None,
        help="ArduPilot checkout (defaults to ARDUPILOT_ROOT)",
    )
    parser.add_argument("--home", default=DEFAULT_HOME, help="lat,lon,altitude,heading")
    parser.add_argument("--model", default="+", help="ArduPilot SITL model")
    parser.add_argument("--gcs-port", type=int, default=14550)
    parser.add_argument("--connector-port", type=int, default=14551)
    return parser


def find_copter_binary(ardupilot_root: Path) -> Path:
    """Find the already-built ArduCopter SITL executable."""

    candidates = (
        ardupilot_root / "build" / "sitl" / "bin" / "arducopter",
        ardupilot_root / "build" / "sitl" / "bin" / "arducopter.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    expected = "\n".join(f"  - {candidate}" for candidate in candidates)
    raise FileNotFoundError(
        "ArduCopter SITL binary was not found. Build it in the ArduPilot checkout "
        "with './waf configure --board sitl' and './waf copter -j2'. Expected:\n"
        f"{expected}"
    )


def build_command(
    binary: Path,
    *,
    home: str = DEFAULT_HOME,
    model: str = "+",
    gcs_port: int = 14550,
    connector_port: int = 14551,
) -> list[str]:
    """Build the portable direct-binary command used by :func:`main`."""

    return [
        str(binary),
        "--model",
        model,
        "--home",
        home,
        "--serial0",
        f"udpclient:127.0.0.1:{gcs_port}",
        "--serial1",
        f"udpclient:127.0.0.1:{connector_port}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configured_root = args.ardupilot_root or os.environ.get("ARDUPILOT_ROOT")
    if not configured_root:
        raise SystemExit("Set ARDUPILOT_ROOT or pass --ardupilot-root.")

    root = Path(configured_root).expanduser().resolve()
    try:
        binary = find_copter_binary(root)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc

    command = build_command(
        binary,
        home=args.home,
        model=args.model,
        gcs_port=args.gcs_port,
        connector_port=args.connector_port,
    )
    print(f"Starting ArduCopter SITL from {root}", flush=True)
    print(f"  GCS output:        udp://127.0.0.1:{args.gcs_port}", flush=True)
    print(f"  Connector output:  udp://127.0.0.1:{args.connector_port}", flush=True)
    print("Press Ctrl+C to stop SITL.", flush=True)
    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
