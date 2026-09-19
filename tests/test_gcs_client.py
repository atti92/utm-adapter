from datetime import datetime, timezone
from uuid import UUID

import httpx

from utm_connector.domain import OperationCommand
from utm_connector.gcs_client import ConnectorClient, ConnectorClientError


def _client(handler):
    transport = httpx.MockTransport(handler)
    return ConnectorClient("http://connector.test", client=httpx.Client(transport=transport))


def test_client_maps_gcs_workflow_to_connector_endpoints() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/qgroundcontrol"):
            return httpx.Response(200, json={"mission_hash": "a" * 64})
        if request.url.path.endswith("/operator-intents"):
            return httpx.Response(200, json={"operation_id": "00000000-0000-0000-0000-000000000001"})
        if request.url.path == "/v1/vehicles":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"status": "ok"})

    operation_id = UUID("00000000-0000-0000-0000-000000000001")
    with _client(handler) as client:
        assert client.health() == {"status": "ok"}
        assert client.vehicles() == []
        assert client.upload_qgroundcontrol_plan(
            "sitl/1",
            {"fileType": "Plan"},
            valid_from=datetime(2030, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2030, 1, 1, 0, 30, tzinfo=timezone.utc),
        )["mission_hash"] == "a" * 64
        client.operation_intent("sitl/1", OperationCommand.SUBMIT_OPERATION, operation_id=operation_id)

    assert requests[2].url.raw_path == b"/v1/missions/sitl%2F1/qgroundcontrol"
    assert requests[2].content.startswith(b'{"valid_from"')
    assert requests[3].url.path == "/v1/operator-intents"
    assert requests[3].url.params["vehicle_id"] == "sitl/1"


def test_client_surfaces_provider_http_errors_without_provider_types() -> None:
    with _client(lambda _request: httpx.Response(409, json={"detail": "operation not found"})) as client:
        try:
            client.refresh_operation("not-found")
        except ConnectorClientError as exc:
            assert exc.status_code == 409
            assert str(exc) == "operation not found"
        else:  # pragma: no cover - assertion guard
            raise AssertionError("expected ConnectorClientError")
