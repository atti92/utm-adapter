import socket
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

from utm_connector.diagnostics import port_is_reachable, probe_http_endpoint


def test_doctor_detects_an_active_listen_port() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        assert port_is_reachable("127.0.0.1", listener.getsockname()[1]) is True
    finally:
        listener.close()


def test_http_probe_passes_auth_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str, *, headers: dict[str, str]):
            captured["url"] = url
            captured["headers"] = headers
            return httpx.Response(200)

    monkeypatch.setattr(httpx, "Client", FakeClient)

    assert probe_http_endpoint(
        "http://127.0.0.1:8000",
        path="/protected",
        headers={"Authorization": "Bearer local-token"},
    ) == (True, "reachable (HTTP 200)")
    assert captured == {
        "timeout": 1.5,
        "url": "http://127.0.0.1:8000/protected",
        "headers": {"Authorization": "Bearer local-token"},
    }


def test_dev_token_has_the_claims_required_by_flight_blender() -> None:
    import base64
    import json

    from scripts.generate_flight_blender_dev_token import generate_token

    _header, encoded_claims, _signature = generate_token().split(".")
    padding = "=" * (-len(encoded_claims) % 4)
    claims = json.loads(base64.urlsafe_b64decode(encoded_claims + padding))

    assert claims["iss"]
    assert claims["aud"] == "testflight.flightblender.com"
    assert "flightblender.write" in claims["scope"]
