from __future__ import annotations

from contextlib import asynccontextmanager
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query

from .backends import BackendError, FlightBlenderBackend, InMemoryBackend
from .config import ConnectorSettings
from .domain import (
    DeclarationState,
    Event,
    HealthResponse,
    Mission,
    OperationCommand,
    OperationIntent,
    QGroundControlMissionRequest,
    VehicleTelemetry,
)
from .runtime import MavlinkSessionManager
from .missions import MissionParseError, parse_qgroundcontrol_plan
from .service import ConnectorError, ConnectorService
from .persistence import SQLiteStateStore
from .recording import JsonlRecorder


def create_app(
    service: Optional[ConnectorService] = None,
    settings: Optional[ConnectorSettings] = None,
    session_manager: Optional[MavlinkSessionManager] = None,
) -> FastAPI:
    settings = settings or ConnectorSettings()
    recorder = None
    if service is None:
        recorder = JsonlRecorder(settings.record_path) if settings.record_path else None
        backend = (
            FlightBlenderBackend(
                settings.flight_blender_base_url,
                bearer_token=settings.flight_blender_bearer_token,
                timeout_s=settings.flight_blender_timeout_s,
                max_retries=settings.flight_blender_max_retries,
                retry_backoff_s=settings.flight_blender_retry_backoff_s,
                type_of_operation=settings.flight_blender_type_of_operation,
                submitted_by=settings.flight_blender_submitted_by,
                originating_party=settings.flight_blender_originating_party,
                recorder=recorder,
            )
            if settings.backend == "flight-blender"
            else InMemoryBackend()
        )
        service = ConnectorService(backend, SQLiteStateStore(settings.state_db_path), recorder=recorder)
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
            close_backend = getattr(service.backend, "close", None)
            if close_backend is not None:
                close_backend()
            if recorder is not None:
                recorder.close()

    app = FastAPI(title="UTM Operations Connector", version="0.1.0", lifespan=lifespan)
    app.state.connector_service = service
    app.state.mavlink_session_manager = manager

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            active_vehicles=len(set(service.vehicles) | set(service.vehicle_snapshots)),
            active_operations=sum(
                operation.state.declaration in {
                    DeclarationState.SUBMITTED,
                    DeclarationState.ACCEPTED,
                }
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

    @app.put("/v1/missions/{vehicle_id}/qgroundcontrol", response_model=dict)
    def put_qgroundcontrol_mission(
        vehicle_id: str, request: QGroundControlMissionRequest
    ) -> dict:
        """Normalize a QGroundControl Plan with explicit UTM metadata."""

        try:
            mission = parse_qgroundcontrol_plan(
                request.plan,
                vehicle_id=vehicle_id,
                valid_from=request.valid_from,
                valid_until=request.valid_until,
                corridor_radius_m=request.corridor_radius_m,
            )
            return service.put_mission(vehicle_id, mission).model_dump(mode="json")
        except (ConnectorError, MissionParseError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid QGroundControl mission: {exc}") from exc

    @app.put("/v1/vehicles/{vehicle_id}/onboard-mission", response_model=dict)
    def put_onboard_mission(vehicle_id: str, mission: Mission) -> dict:
        try:
            return service.put_onboard_mission(vehicle_id, mission).model_dump(mode="json")
        except ConnectorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/vehicles/{vehicle_id}/onboard-mission/refresh", response_model=dict, status_code=202)
    def refresh_onboard_mission(vehicle_id: str) -> dict:
        try:
            manager.request_mission(vehicle_id)
        except (ConnectorError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"vehicle_id": vehicle_id, "status": "REQUESTED"}

    @app.put("/v1/vehicles/{vehicle_id}", response_model=VehicleTelemetry)
    def put_telemetry(vehicle_id: str, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        try:
            return service.put_telemetry(vehicle_id, telemetry)
        except BackendError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/operator-intents", response_model=dict, status_code=201)
    def operator_intent(intent: OperationIntent, vehicle_id: str = Query(...)) -> dict:
        try:
            if intent.command == OperationCommand.SUBMIT_OPERATION:
                operation = service.submit_operation(intent, vehicle_id)
            else:
                operation = service.apply_intent(intent)
        except BackendError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ConnectorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return operation.model_dump(mode="json")

    @app.get("/v1/operations/{operation_id}", response_model=dict)
    def get_operation(operation_id: UUID) -> dict:
        operation = service.operations.get(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation.model_dump(mode="json")

    @app.post("/v1/operations/{operation_id}/refresh", response_model=dict)
    def refresh_operation(operation_id: UUID) -> dict:
        try:
            return service.refresh_operation(operation_id).model_dump(mode="json")
        except BackendError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ConnectorError as exc:
            status_code = 404 if str(exc) == "operation not found" else 409
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

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
