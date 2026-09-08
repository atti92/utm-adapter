# Local development environment

The repository now contains a Phase 0 connector skeleton based on the implementation plan. It runs a loopback-only FastAPI service with an in-memory backend, so product behavior can be exercised without credentials or a deployed UTM provider.

## Requirements

- Python 3.9 or newer
- [uv](https://docs.astral.sh/uv/)

## Start the local connector

```sh
uv sync
uv run utm-connector
```

Convenience targets are also available: `make setup`, `make test`, and `make run`.

The service listens on `http://127.0.0.1:8000`. OpenAPI is available at `/docs`, and the health endpoint is `/v1/health`.

## Run tests

```sh
uv run pytest
```

## Exercise the API

Upload a mission, submit it, start it, and publish telemetry:

```sh
curl -X PUT http://127.0.0.1:8000/v1/missions/sitl-1 \
  -H 'content-type: application/json' \
  -d @tests/fixtures/example-mission.json

curl -X POST 'http://127.0.0.1:8000/v1/operator-intents?vehicle_id=sitl-1' \
  -H 'content-type: application/json' \
  -d '{"schema_version":"1.0","command":"SUBMIT_OPERATION","operation_id":"00000000-0000-0000-0000-000000000001"}'
```

The local backend accepts the declaration and marks it authorized to make the happy-path lifecycle testable. This is a development behavior; the backend adapter interface is deliberately separate so real authorization semantics can be implemented later.
