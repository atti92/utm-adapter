from fastapi.testclient import TestClient

from utm_connector.api import create_app
from utm_connector.backends import InMemoryBackend
from utm_connector.service import ConnectorService


def test_operator_console_is_served_without_external_assets() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))

    response = client.get("/ui/")

    assert response.status_code == 200
    assert "UTM Operator Console" in response.text
    assert "/ui/app.js" in response.text
    assert "/ui/styles.css" in response.text


def test_operator_console_contains_the_complete_gcs_workflow() -> None:
    client = TestClient(create_app(ConnectorService(InMemoryBackend())))

    html = client.get("/ui/").text
    javascript = client.get("/ui/app.js").text

    for label in ("Open .plan", "Validate &amp; save", "Submit to UTM", "Start operation", "Cancel"):
        assert label in html
    for endpoint in (
        "/v1/health",
        "/v1/vehicles",
        "/v1/missions/",
        "/v1/operator-intents",
        "/v1/operations/",
    ):
        assert endpoint in javascript
