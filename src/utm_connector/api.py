from __future__ import annotations

from contextlib import asynccontextmanager
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query

from .backends import InMemoryBackend
from .config import ConnectorSettings
from .domain import DeclarationState, Event, HealthResponse, Mission, OperationCommand, OperationIntent, VehicleTelemetry
from .runtime import MavlinkSessionManager
from .service import ConnectorError, ConnectorService


def create_app(
    service: Optional[ConnectorService] = None,
    settings: Optional[ConnectorSettings] = None,
    session_manager: Optional[MavlinkSessionManager] = None,
) -> FastAPI:
    service = service or ConnectorService(InMemoryBackend())
    settings = settings or ConnectorSettings()
    manager = session_manager or MavlinkSessionManager(
        settings.mavlink_connections,
        service.ingest_vehicle_snapshot,
        poll_interval_s=settings.mavlink_poll_interval_s,
        on_error=lambda vehicle_id, error: service.record_event(
            "MAVLINK_SESSION_ERROR",
            vehicle_id=vehicle_id,
            severity="ERROR",
            details={"error": str(error)},
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.start()
        try:
            yield
        finally:
            manager.stop()

    app = FastAPI(title="UTM Operations Connector", version="0.1.0", lifespan=lifespan)
    app.state.connector_service = service
    app.state.mavlink_session_manager = manager

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            active_vehicles=len(set(service.vehicles) | set(service.vehicle_snapshots)),
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

    @app.put("/v1/vehicles/{vehicle_id}/onboard-mission", response_model=dict)
    def put_onboard_mission(vehicle_id: str, mission: Mission) -> dict:
        try:
            return service.put_onboard_mission(vehicle_id, mission).model_dump(mode="json")
        except ConnectorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
        vehicle_snapshot = service.vehicle_snapshots.get(vehicle_id)
        if telemetry is None and vehicle_snapshot is None:
            raise HTTPException(status_code=404, detail="vehicle not found")
        operations = [
            operation.model_dump(mode="json")
            for operation in service.operations.values()
            if operation.vehicle_id == vehicle_id
        ]
        return {
            "vehicle_id": vehicle_id,
            "vehicle_state": vehicle_snapshot.model_dump(mode="json") if vehicle_snapshot else None,
            "latest_telemetry": telemetry.model_dump(mode="json") if telemetry else None,
            "mission_drift": (
                service.mission_drifts[vehicle_id].model_dump(mode="json")
                if vehicle_id in service.mission_drifts
                else None
            ),
            "operations": operations,
        }

    @app.get("/v1/events", response_model=List[Event])
    def events(limit: int = Query(default=100, ge=1, le=1000)) -> List[Event]:
        return list(reversed(service.events[-limit:]))

    return app


app = create_app()
