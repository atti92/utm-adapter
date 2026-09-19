"""Small environment diagnostics shared by developer tooling."""

from __future__ import annotations

import socket

import httpx


def port_is_reachable(host: str, port: int) -> bool:
    """Return whether a local process is already accepting the configured port."""

    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.2):
            return True
    except OSError:
        return False


def probe_http_endpoint(base_url: str, path: str = "/ping", timeout_s: float = 1.5) -> tuple[bool, str]:
    """Probe a local HTTP dependency without raising setup-tool exceptions."""

    url = f"{base_url.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(url)
    except httpx.RequestError as exc:
        return False, f"not reachable ({exc.__class__.__name__})"
    if 200 <= response.status_code < 300:
        return True, f"reachable (HTTP {response.status_code})"
    return False, f"responded with HTTP {response.status_code}"
