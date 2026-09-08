from __future__ import annotations

import os

import uvicorn


def run() -> None:
    uvicorn.run(
        "utm_connector.api:app",
        host=os.getenv("UTM_CONNECTOR_HOST", "127.0.0.1"),
        port=int(os.getenv("UTM_CONNECTOR_PORT", "8000")),
        log_level=os.getenv("UTM_CONNECTOR_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    run()

