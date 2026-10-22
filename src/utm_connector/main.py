from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser

import uvicorn

from . import __version__
from .config import ConnectorSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the local UTM operator console")
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="open the operator console in the default browser after startup",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="run a self-contained moving-vehicle demo with the in-memory backend",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="load connector defaults from a JSON configuration file",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"utm-connector {__version__}",
    )
    return parser


def run() -> None:
    args, _unknown = _parser().parse_known_args()
    if args.config:
        os.environ["UTM_CONNECTOR_CONFIG_FILE"] = args.config
    if args.demo:
        # The app is loaded by Uvicorn's factory in a separate import step, so
        # pass this explicit CLI override through the same environment-backed
        # settings boundary used by normal installations.
        os.environ["UTM_CONNECTOR_BACKEND"] = "in-memory"
        os.environ["UTM_CONNECTOR_DEMO_MODE"] = "true"
        os.environ["UTM_CONNECTOR_MAVLINK_CONNECTIONS"] = "[]"
        # Presentation runs should always start from a clean state. Normal
        # runs keep the configured SQLite history; only the explicit demo
        # shortcut uses an in-memory store.
        os.environ["UTM_CONNECTOR_STATE_DB_PATH"] = ":memory:"
    try:
        settings = ConnectorSettings()
    except Exception as exc:
        print("UTM Connector configuration error:", file=sys.stderr)
        print(f"{exc}", file=sys.stderr)
        print("Run `uv run python scripts/doctor.py` for setup guidance.", file=sys.stderr)
        raise SystemExit(2) from exc
    if args.open_browser:
        url = f"http://{settings.host}:{settings.port}/"
        browser_timer = threading.Timer(1.0, webbrowser.open, args=(url,))
        browser_timer.daemon = True
        browser_timer.start()
    uvicorn.run(
        "utm_connector.api:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    run()
