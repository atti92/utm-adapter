"""Validate the checked-in MAVLink Router fan-out configuration.

This check is useful on every host: the configuration contract can be
verified without running a vehicle or installing mavlink-routerd.  Strict
mode additionally requires the router executable so a demo machine can fail
early with an actionable message.
"""

from __future__ import annotations

import argparse
import configparser
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "examples" / "mavlink-router" / "main.conf"


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
    """Return configuration errors for the connector's documented topology."""

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
            "address": "127.0.0.1",
            "port": "14550",
        },
        "UdpEndpoint utm_connector": {
            "mode": "Normal",
            "address": "127.0.0.1",
            "port": "14551",
        },
        "UdpEndpoint vehicle_input": {
            "mode": "Server",
            "address": "0.0.0.0",
            "port": "14560",
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
        port = values.get("port")
        if port:
            previous = seen_ports.get(port)
            if previous:
                errors.append(f"router UDP port {port} is used by both {previous} and {section}")
            else:
                seen_ports[port] = section

    return errors


def _router_binary() -> str | None:
    return shutil.which("mavlink-routerd")


def main() -> int:
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
        help="also require mavlink-routerd to be installed",
    )
    args = parser.parse_args()
    config_path = args.router_config.expanduser().resolve()
    errors = validate(config_path)
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 1

    print(f"[ok] MAVLink Router topology is valid: {config_path}")
    binary = _router_binary()
    if binary:
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
    elif args.strict:
        print("[error] mavlink-routerd is not installed or not on PATH")
        return 1
    else:
        print("[info] mavlink-routerd is not installed; install it before the live router demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
