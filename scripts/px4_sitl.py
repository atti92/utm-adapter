"""Launch a PX4 SITL vehicle for local connector testing.

PX4 publishes the normal ground-station MAVLink stream on remote UDP port
14550 and the external-API stream on remote UDP port 14540.  Keeping those
streams separate is useful for a local demo: QGroundControl can keep its
normal port while the connector listens independently on the API port.

The official PX4 SITL container is the default because it is available on
macOS, Linux, WSL, and Windows without requiring a native PX4 toolchain.  A
local checkout is still supported for teams that build PX4 themselves; the
helper only starts an already-built binary in that mode and leaves the exact
build workflow to PX4's own documentation.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


DEFAULT_MODEL = "sihsim_quadx"
DEFAULT_GCS_PORT = 14550
# PX4's remote external-API endpoint is 14540 inside the container. Preserve
# that host/remote pairing because the stock image's default remote address is
# localhost:14540; Docker forwards this stream reliably when the published
# host port remains 14540 as well.
DEFAULT_CONNECTOR_PORT = 14540
PX4_EXTERNAL_API_PORT = 14540
DEFAULT_DOCKER_IMAGE = "px4io/px4-sitl:latest"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch PX4 SITL with separate GCS and connector MAVLink outputs"
    )
    parser.add_argument(
        "--px4-root",
        type=Path,
        default=None,
        help="optional PX4 checkout containing an already-built SITL binary",
    )
    parser.add_argument(
        "--docker-image",
        default=os.environ.get("PX4_SITL_IMAGE", DEFAULT_DOCKER_IMAGE),
        help=f"PX4 SITL container image (default: {DEFAULT_DOCKER_IMAGE})",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="PX4 SITL model")
    parser.add_argument("--gcs-port", type=int, default=DEFAULT_GCS_PORT)
    parser.add_argument("--connector-port", type=int, default=DEFAULT_CONNECTOR_PORT)
    parser.add_argument(
        "--container-name",
        default=None,
        help="optional Docker container name (useful for external diagnostics)",
    )
    parser.add_argument(
        "--local-binary",
        action="store_true",
        help="run a built PX4 binary from --px4-root instead of Docker",
    )
    return parser


def find_px4_binary(px4_root: Path) -> Path:
    """Find a built PX4 SITL executable in a checkout."""

    candidates = (
        px4_root / "build" / "px4_sitl_default" / "bin" / "px4",
        px4_root / "build" / "px4_sitl_default" / "bin" / "px4.exe",
        px4_root / "build" / "px4_sitl_sih" / "bin" / "px4",
        px4_root / "build" / "px4_sitl_sih" / "bin" / "px4.exe",
        px4_root / "build" / "px4_sitl_default" / "px4",
        px4_root / "build" / "px4_sitl_sih" / "px4",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    expected = "\n".join(f"  - {candidate}" for candidate in candidates)
    raise FileNotFoundError(
        "PX4 SITL binary was not found. Build PX4 with its documented SITL "
        "target (for example, `make px4_sitl_sih sihsim_quadx`). Expected:\n"
        f"{expected}"
    )


def build_docker_command(
    image: str = DEFAULT_DOCKER_IMAGE,
    *,
    model: str = DEFAULT_MODEL,
    gcs_port: int = DEFAULT_GCS_PORT,
    connector_port: int = DEFAULT_CONNECTOR_PORT,
    container_name: str | None = None,
) -> list[str]:
    """Build the documented, cross-platform PX4 SITL Docker command."""

    command = ["docker", "run", "--rm", "--init"]
    if container_name:
        command.extend(["--name", container_name])
    command.extend(
        [
            "-p",
            f"{gcs_port}:14550/udp",
            "-p",
            f"{connector_port}:{PX4_EXTERNAL_API_PORT}/udp",
            "-e",
            f"PX4_SIM_MODEL={model}",
            image,
        ]
    )
    return command


def build_local_command(binary: Path, *, model: str = DEFAULT_MODEL) -> list[str]:
    """Build the minimal direct-binary command for a pre-built PX4 checkout."""

    # PX4's POSIX SITL binary reads the model from PX4_SIM_MODEL.  The caller
    # supplies that environment variable in ``main``; keeping the command
    # itself small makes it easy to inspect and test on every host.
    return [str(binary)]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.gcs_port <= 65535 or not 1 <= args.connector_port <= 65535:
        raise SystemExit("MAVLink UDP ports must be between 1 and 65535.")
    if args.gcs_port == args.connector_port:
        raise SystemExit("GCS UDP port and connector UDP port must be different.")
    if args.gcs_port != DEFAULT_GCS_PORT:
        raise SystemExit(
            "The stock PX4 SITL image sends its GCS stream to UDP "
            f"{DEFAULT_GCS_PORT}; keep --gcs-port at that value or use a MAVLink "
            "router for custom host ports."
        )
    if args.connector_port != PX4_EXTERNAL_API_PORT:
        raise SystemExit(
            "The stock PX4 SITL image sends its external-API stream to UDP "
            f"{PX4_EXTERNAL_API_PORT}; keep --connector-port at that value or "
            "use a MAVLink router for custom host ports."
        )

    if args.local_binary:
        configured_root = args.px4_root or os.environ.get("PX4_ROOT")
        if not configured_root:
            raise SystemExit("Set PX4_ROOT or pass --px4-root with --local-binary.")
        root = Path(configured_root).expanduser().resolve()
        try:
            binary = find_px4_binary(root)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
        command = build_local_command(binary, model=args.model)
        env = os.environ.copy()
        env["PX4_SIM_MODEL"] = args.model
        print(f"Starting local PX4 SITL from {root}", flush=True)
        print(f"  GCS output:        udp://127.0.0.1:{args.gcs_port} (PX4 default 14550)", flush=True)
        print(f"  Connector output:  udp://127.0.0.1:{args.connector_port} (PX4 default 14540)", flush=True)
        return subprocess.call(command, cwd=root, env=env)

    if shutil.which("docker") is None:
        raise SystemExit("Docker is required for the portable PX4 SITL launcher.")
    command = build_docker_command(
        args.docker_image,
        model=args.model,
        gcs_port=args.gcs_port,
        connector_port=args.connector_port,
        container_name=args.container_name,
    )
    print(f"Starting PX4 SITL container {args.docker_image}", flush=True)
    print(f"  GCS output:        udp://127.0.0.1:{args.gcs_port} (PX4 remote 14550)", flush=True)
    print(f"  Connector output:  udp://127.0.0.1:{args.connector_port} (PX4 remote 14540)", flush=True)
    print("Press Ctrl+C to stop SITL.", flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
