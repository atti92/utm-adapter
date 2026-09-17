"""Validate the local connector environment without starting services."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utm_connector.config import ConnectorSettings
from utm_connector.diagnostics import port_is_reachable


def _check(label: str, detail: str) -> None:
    print(f"[ok] {label}: {detail}")


def _info(label: str, detail: str) -> None:
    print(f"[info] {label}: {detail}")


def main() -> int:
    print("UTM Operations Connector setup doctor")
    print("=====================================")

    version = sys.version_info
    if (3, 10) <= (version.major, version.minor) < (3, 14):
        _check("Python", f"{version.major}.{version.minor}.{version.micro}")
    else:
        print(
            f"[fail] Python: {version.major}.{version.minor}.{version.micro}; "
            "supported versions are 3.10 through 3.13"
        )
        return 1

    try:
        settings = ConnectorSettings()
    except Exception as exc:
        print(f"[fail] configuration: {exc}")
        print("       Copy .env.example to .env and fix the reported setting.")
        return 1

    _check("configuration", f"backend={settings.backend}, listen={settings.host}:{settings.port}")
    _check("event history", f"keeping the latest {settings.event_history_limit} events in memory")
    if port_is_reachable(settings.host, settings.port):
        _info(
            "listen port",
            f"{settings.host}:{settings.port} already has a listener; stop it or choose another port",
        )
    else:
        _check("listen port", f"{settings.host}:{settings.port} is available")

    if Path(".env").exists():
        _check("environment file", ".env found")
    else:
        _info("environment file", ".env not found; built-in defaults will be used")

    if settings.state_db_path == ":memory:":
        _check("state database", "in-memory (data is discarded on shutdown)")
    else:
        state_path = Path(settings.state_db_path)
        parent = state_path.parent
        if parent.exists() and os.access(parent, os.W_OK):
            _check("state database", f"{state_path} is writable")
        elif not parent.exists() and parent.parent.exists() and os.access(parent.parent, os.W_OK):
            _info("state database", f"{state_path} parent will be created on startup")
        else:
            print(f"[fail] state database: cannot write to {state_path}")
            return 1

    if settings.backend == "flight-blender":
        _check("Flight Blender", settings.flight_blender_base_url)
        if not settings.flight_blender_bearer_token:
            _info("Flight Blender token", "empty; local development bypass may still require a generated token")
    else:
        _check("UTM backend", "in-memory; no external UTM service is required")

    if settings.mavlink_connections:
        for connection in settings.mavlink_connections:
            _check("MAVLink", f"{connection.vehicle_id} -> {connection.connection_uri}")
    else:
        _info("MAVLink", "no connections configured; connector will run without live vehicles")

    print("\nNext steps:")
    print("  uv run python scripts/local_smoke.py  # exercise the API in-process")
    print("  uv run utm-connector                  # start the local API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
