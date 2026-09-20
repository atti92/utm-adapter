"""Validate the local connector environment without starting services."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utm_connector.altitude import AltitudeConversionError, AltitudeConverter
from utm_connector.config import ConnectorSettings
from utm_connector.diagnostics import port_is_reachable, probe_http_endpoint


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
        provider_ok, provider_detail = probe_http_endpoint(settings.flight_blender_base_url)
        report_provider = _check if provider_ok else _info
        report_provider(
            "Flight Blender",
            f"{settings.flight_blender_base_url} ({provider_detail})",
        )
        if not settings.flight_blender_bearer_token:
            _info("Flight Blender token", "empty; local development bypass may still require a generated token")
        elif provider_ok:
            auth_ok, auth_detail = probe_http_endpoint(
                settings.flight_blender_base_url,
                path="/flight_declaration_ops/flight_declaration",
                headers={"Authorization": f"Bearer {settings.flight_blender_bearer_token}"},
            )
            if auth_ok:
                _check("Flight Blender auth", auth_detail)
            else:
                print(f"[fail] Flight Blender auth: {auth_detail}")
                return 1
        else:
            _info("Flight Blender auth", "not checked because the provider is not reachable")
    else:
        _check("UTM backend", "in-memory; no external UTM service is required")

    if settings.altitude_geoid_grid_path:
        try:
            AltitudeConverter(settings.altitude_geoid_grid_path)
        except AltitudeConversionError as exc:
            print(f"[fail] altitude conversion: {exc}")
            return 1
        _check("altitude conversion", f"geoid grid {settings.altitude_geoid_grid_path}")
    elif settings.backend == "flight-blender":
        _info(
            "altitude conversion",
            "not configured; AMSL MAVLink telemetry cannot be declared as WGS84 safely",
        )

    if settings.demo_mode:
        if settings.backend != "in-memory":
            print("[fail] demo mode: it requires UTM_CONNECTOR_BACKEND=in-memory")
            return 1
        _check("demo mode", f"{settings.demo_vehicle_id} at {settings.demo_interval_s:.1f}s intervals")

    if settings.mavlink_connections:
        for connection in settings.mavlink_connections:
            _check("MAVLink", f"{connection.vehicle_id} -> {connection.connection_uri}")
    else:
        _info("MAVLink", "no connections configured; connector will run without live vehicles")

    print("\nNext steps:")
    print("  uv run python scripts/local_smoke.py  # exercise the API in-process")
    print("  uv run utm-connector                  # start the local API")
    print("  uv run python scripts/openutm_demo.py --simulator px4 --check")
    print("                                         # full GCS + Flight Blender preflight")
    print("  make demo-check                       # required + optional integration preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
