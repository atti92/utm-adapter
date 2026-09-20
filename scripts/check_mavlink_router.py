"""Validate the checked-in MAVLink Router fan-out configuration.

This check is useful on every host: the configuration contract can be
verified without running a vehicle or installing mavlink-routerd.  Strict
mode additionally requires a usable router runtime so a demo machine can fail
early with an actionable message.  The runtime can be a native
``mavlink-routerd`` binary or the portable Docker fallback used by the
supervised demo.
"""

from __future__ import annotations

import argparse
import configparser
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "examples" / "mavlink-router" / "main.conf"
DEFAULT_RUNTIME = "auto"
DEFAULT_IMAGE = "utm-adapter-mavlink-router:local"
DEFAULT_SOURCE_ROOT = ROOT.parent / "mavlink-router"


def _read_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # preserve router option names for diagnostics
    try:
        with path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except OSError as exc:
        raise ValueError(f"could not read router config {path}: {exc}") from exc
    except configparser.Error as exc:
        raise ValueError(f"invalid router config {path}: {exc}") from exc
    return parser


def _section_values(parser: configparser.ConfigParser, section: str) -> dict[str, str]:
    if not parser.has_section(section):
        raise ValueError(f"missing [{section}] section")
    return {key.lower(): value.strip() for key, value in parser.items(section)}


def validate(path: Path) -> list[str]:
    """Return errors for the documented consumer fan-out topology.

    The consumer endpoints are shared by the local SITL example and the
    production companion-computer example. The vehicle input can therefore be
    either the checked-in UDP server used by SITL or a UART endpoint connected
    to the physical telemetry link.
    """

    try:
        parser = _read_config(path)
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []
    general = _section_values(parser, "General") if parser.has_section("General") else {}
    if general.get("tcpserverport") != "5760":
        errors.append("[General] TcpServerPort must be 5760 for the documented topology")

    expected = {
        "UdpEndpoint qgroundcontrol": {
            "mode": "Normal",
            "port": "14550",
        },
        "UdpEndpoint utm_connector": {
            "mode": "Normal",
            "port": "14551",
        },
    }
    seen_ports: dict[str, str] = {}
    for section, required in expected.items():
        try:
            values = _section_values(parser, section)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for key, expected_value in required.items():
            actual = values.get(key)
            if actual != expected_value:
                errors.append(f"[{section}] {key} must be {expected_value!r} (got {actual!r})")
        if not values.get("address"):
            errors.append(f"[{section}] address must not be empty")
        port = values.get("port")
        if port:
            previous = seen_ports.get(port)
            if previous:
                errors.append(f"router UDP port {port} is used by both {previous} and {section}")
            else:
                seen_ports[port] = section

    has_uart_input = parser.has_section("UartEndpoint vehicle_link")
    has_udp_input = parser.has_section("UdpEndpoint vehicle_input")
    if has_uart_input and has_udp_input:
        errors.append(
            "configure either [UartEndpoint vehicle_link] or "
            "[UdpEndpoint vehicle_input], not both"
        )
    elif has_uart_input:
        values = _section_values(parser, "UartEndpoint vehicle_link")
        if not values.get("device"):
            errors.append("[UartEndpoint vehicle_link] Device must not be empty")
        baud = values.get("baud", "")
        if not baud.isdigit() or int(baud) <= 0:
            errors.append("[UartEndpoint vehicle_link] Baud must be a positive integer")
    elif has_udp_input:
        required = {
            "mode": "Server",
            "address": "0.0.0.0",
            "port": "14560",
        }
        values = _section_values(parser, "UdpEndpoint vehicle_input")
        for key, expected_value in required.items():
            actual = values.get(key)
            if actual != expected_value:
                errors.append(
                    f"[UdpEndpoint vehicle_input] {key} must be {expected_value!r} "
                    f"(got {actual!r})"
                )
        port = values.get("port")
        if port:
            previous = seen_ports.get(port)
            if previous:
                errors.append(
                    f"router UDP port {port} is used by both {previous} and "
                    "[UdpEndpoint vehicle_input]"
                )
            else:
                seen_ports[port] = "[UdpEndpoint vehicle_input]"
    else:
        errors.append(
            "missing vehicle input: add [UartEndpoint vehicle_link] for a "
            "physical link or [UdpEndpoint vehicle_input] for SITL"
        )

    return errors


def _router_binary() -> str | None:
    configured = os.environ.get("MAVLINK_ROUTERD")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which("mavlink-routerd")


def _docker_available() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["docker", "version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def _docker_image_is_available(image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _docker_fallback_error(source_root: Path, image: str) -> str | None:
    docker_ok, docker_detail = _docker_available()
    if not docker_ok:
        return f"Docker is unavailable for the router fallback: {docker_detail or 'command failed'}"
    if _docker_image_is_available(image):
        return None
    dockerfile = source_root / "examples" / "Dockerfile.ubuntu"
    if not source_root.is_dir():
        return (
            "MAVLink Router source checkout not found for the Docker fallback: "
            f"{source_root} (set MAVLINK_ROUTER_ROOT)"
        )
    if not dockerfile.is_file():
        return f"MAVLink Router Dockerfile not found: {dockerfile}"
    return None


def _select_runtime(runtime: str, source_root: Path, image: str) -> str | None:
    if runtime == "native":
        return "native" if _router_binary() else None
    if runtime == "docker":
        return "docker" if _docker_fallback_error(source_root, image) is None else None
    if runtime != "auto":
        return None
    if _router_binary():
        return "native"
    return "docker" if _docker_fallback_error(source_root, image) is None else None


def _print_native_status(binary: str) -> None:
    try:
        result = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        detail = (result.stdout or result.stderr).strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        detail = []
    suffix = f" ({detail[0]})" if detail else ""
    print(f"[ok] mavlink-routerd: {binary}{suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--router-config",
        type=Path,
        default=Path(os.environ.get("MAVLINK_ROUTER_CONFIG", DEFAULT_CONFIG)),
        help="mavlink-routerd config to validate (default: checked-in main.conf)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also require a usable native or Docker router runtime",
    )
    parser.add_argument(
        "--router-runtime",
        choices=("auto", "native", "docker"),
        default=os.environ.get("MAVLINK_ROUTER_RUNTIME", DEFAULT_RUNTIME),
        help="router runtime to check (default: auto-select native then Docker)",
    )
    parser.add_argument(
        "--router-source-root",
        type=Path,
        default=Path(os.environ.get("MAVLINK_ROUTER_ROOT", DEFAULT_SOURCE_ROOT)),
        help="MAVLink Router checkout used to build the Docker fallback",
    )
    parser.add_argument(
        "--router-image",
        default=os.environ.get("MAVLINK_ROUTER_IMAGE", DEFAULT_IMAGE),
        help=f"Docker router image (default: {DEFAULT_IMAGE})",
    )
    args = parser.parse_args(argv)
    config_path = args.router_config.expanduser().resolve()
    errors = validate(config_path)
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 1

    print(f"[ok] MAVLink Router topology is valid: {config_path}")
    source_root = args.router_source_root.expanduser().resolve()
    runtime = _select_runtime(args.router_runtime, source_root, args.router_image)
    runtime_required = args.strict or args.router_runtime != "auto"
    if runtime == "native":
        binary = _router_binary()
        if binary is not None:
            _print_native_status(binary)
        else:  # pragma: no cover - runtime selection guards this branch
            print("[error] mavlink-routerd is not installed or not on PATH")
            return 1
    elif runtime == "docker":
        if _docker_image_is_available(args.router_image):
            print(f"[ok] Docker MAVLink Router image: {args.router_image}")
        else:
            print(
                "[ok] Docker MAVLink Router fallback: source checkout available "
                f"at {source_root} (image will be built on first live run)"
            )
    elif runtime_required:
        if args.router_runtime == "native":
            print("[error] mavlink-routerd is not installed or not on PATH")
        else:
            reason = _docker_fallback_error(source_root, args.router_image)
            print(
                "[error] no usable MAVLink Router runtime; "
                f"{reason or 'install mavlink-routerd or prepare the Docker fallback'}"
            )
        return 1
    else:
        print(
            "[info] MAVLink Router runtime not available; "
            "install mavlink-routerd or prepare the Docker fallback before a live demo"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
