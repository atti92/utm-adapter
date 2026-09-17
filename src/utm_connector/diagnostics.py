"""Small environment diagnostics shared by developer tooling."""

from __future__ import annotations

import socket


def port_is_reachable(host: str, port: int) -> bool:
    """Return whether a local process is already accepting the configured port."""

    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.2):
            return True
    except OSError:
        return False
