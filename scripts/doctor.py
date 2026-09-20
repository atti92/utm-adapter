"""Validate the local connector environment without starting services."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

from utm_connector.altitude import AltitudeConversionError, AltitudeConverter
from utm_connector.auth import OAuthClientCredentials, OAuthError
from utm_connector.config import ConnectorSettings
from utm_connector.credentials import CredentialStoreError, resolve_client_secret
from utm_connector.diagnostics import port_is_reachable, probe_http_endpoint


def _check(label: str, detail: str) -> None:
    print(f"[ok] {label}: {detail}")


def _info(label: str, detail: str) -> None:
    print(f"[info] {label}: {detail}")


def _python_detail(version: sys.version_info) -> tuple[bool, str]:
    """Return the support result and operator-facing explanation for Python."""

    version_text = f"{version.major}.{version.minor}.{version.micro}"
    if (3, 11) <= (version.major, version.minor) < (3, 14):
        return True, version_text
    if (version.major, version.minor) == (3, 10):
        return (
            True,
            f"{version_text} (transitional compatibility; remove after October 2026)",
        )
    return False, f"{version_text}; supported versions are Python 3.10 through 3.13"


def main() -> int:
    print("UTM Operations Connector setup doctor")
    print("=====================================")

    version = sys.version_info
    python_ok, python_detail = _python_detail(version)
    if python_ok:
        _check("Python", python_detail)
    else:
        print(f"[fail] Python: {python_detail}")
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
        try:
            flight_blender_client_secret = resolve_client_secret(
                client_secret=settings.flight_blender_client_secret,
                keyring_service=settings.flight_blender_client_secret_keyring_service,
                keyring_account=settings.flight_blender_client_secret_keyring_account,
            )
        except CredentialStoreError as exc:
            print(f"[fail] Flight Blender auth: {exc}")
            return 1
        provider_ok, provider_detail = probe_http_endpoint(settings.flight_blender_base_url)
        report_provider = _check if provider_ok else _info
        report_provider(
            "Flight Blender",
            f"{settings.flight_blender_base_url} ({provider_detail})",
        )
        if provider_ok:
            if (
                settings.flight_blender_token_url
                and settings.flight_blender_client_id
                and flight_blender_client_secret
            ):
                try:
                    with httpx.Client(timeout=settings.flight_blender_timeout_s) as client:
                        token = OAuthClientCredentials(
                            settings.flight_blender_token_url,
                            settings.flight_blender_client_id,
                            flight_blender_client_secret,
                            scope=settings.flight_blender_scope,
                            client=client,
                        ).get_token()
                    auth_ok, auth_detail = probe_http_endpoint(
                        settings.flight_blender_base_url,
                        path="/flight_declaration_ops/flight_declaration",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                except (OAuthError, httpx.HTTPError) as exc:
                    print(f"[fail] Flight Blender auth: OAuth token request failed: {exc}")
                    return 1
                if auth_ok:
                    _check("Flight Blender auth", f"OAuth client credentials ({auth_detail})")
                else:
                    print(f"[fail] Flight Blender auth: {auth_detail}")
                    return 1
            elif settings.flight_blender_bearer_token:
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
                _info("Flight Blender auth", "empty; local development bypass may still require a generated token")
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
    print("  Browser console works on every platform; QGroundControl is optional")
    print("  Mission Planner is an optional Windows GCS integration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
