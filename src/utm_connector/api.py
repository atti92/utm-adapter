from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query

from .backends import InMemoryBackend
from .domain import DeclarationState, Event, HealthResponse, Mission, OperationCommand, OperationIntent, VehicleTelemetry
from .service import ConnectorError, ConnectorService


def create_app(service: Optional[ConnectorService] = None) -> FastAPI:
    service = service or ConnectorService(InMemoryBackend())
    app = FastAPI(title="UTM Operations Connector", version="0.1.0")
    app.state.connector_service = service

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            active_vehicles=len(service.vehicles),
            active_operations=sum(
                operation.state.declaration != DeclarationState.CANCELLED
                for operation in service.operations.values()
            ),
            backend=service.backend.name,
        )

    @app.put("/v1/missions/{vehicle_id}", response_model=dict)
    def put_mission(vehicle_id: str, mission: Mission) -> dict:
        try:
            snapshot = service.put_mission(vehicle_id, mission)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return snapshot.model_dump(mode="json")

    @app.put("/v1/vehicles/{vehicle_id}", response_model=VehicleTelemetry)
    def put_telemetry(vehicle_id: str, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        try:
            return service.put_telemetry(vehicle_id, telemetry)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/operator-intents", response_model=dict, status_code=201)
    def operator_intent(intent: OperationIntent, vehicle_id: str = Query(...)) -> dict:
        try:
            if intent.command == OperationCommand.SUBMIT_OPERATION:
                operation = service.submit_operation(intent, vehicle_id)
            else:
                operation = service.apply_intent(intent)
        except ConnectorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return operation.model_dump(mode="json")

    @app.get("/v1/operations/{operation_id}", response_model=dict)
    def get_operation(operation_id: UUID) -> dict:
        operation = service.operations.get(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation.model_dump(mode="json")

    @app.get("/v1/vehicles/{vehicle_id}/status", response_model=dict)
    def vehicle_status(vehicle_id: str) -> dict:
        telemetry = service.vehicles.get(vehicle_id)
        if telemetry is None:
            raise HTTPException(status_code=404, detail="vehicle not found")
        operations = [
            operation.model_dump(mode="json")
            for operation in service.operations.values()
            if operation.vehicle_id == vehicle_id
        ]
        return {"vehicle_id": vehicle_id, "latest_telemetry": telemetry.model_dump(mode="json"), "operations": operations}

    @app.get("/v1/events", response_model=List[Event])
    def events(limit: int = Query(default=100, ge=1, le=1000)) -> List[Event]:
        return list(reversed(service.events[-limit:]))

    return app


app = create_app()
