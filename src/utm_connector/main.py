from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

import uvicorn

from .config import ConnectorSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the local UTM operator console")
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="open the operator console in the default browser after startup",
    )
    return parser


def run() -> None:
    settings = ConnectorSettings()
    args, _unknown = _parser().parse_known_args()
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
