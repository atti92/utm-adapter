from __future__ import annotations

import uvicorn

from .config import ConnectorSettings


def run() -> None:
    settings = ConnectorSettings()
    uvicorn.run(
        "utm_connector.api:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    run()
