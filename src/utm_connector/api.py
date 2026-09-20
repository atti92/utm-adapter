from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .backends import BackendError, FlightBlenderBackend, InMemoryBackend
from .altitude import AltitudeConversionError, AltitudeConverter
from .config import ConnectorSettings
from .demo import DemoVehiclePublisher
from .domain import (
    DeclarationState,
    Event,
    HealthResponse,
    Mission,
    MissionPlannerMissionRequest,
    OperationCommand,
    OperationIntent,
    QGroundControlMissionRequest,
    VehicleTelemetry,
)
from .mavlink import MavlinkVehicleSession
from .observability import RuntimeMetrics
from .runtime import MavlinkSessionManager
from .missions import (
    NAVIGABLE_MISSION_COMMANDS_INFO,
    MissionParseError,
    parse_mission_planner_waypoints,
    parse_qgroundcontrol_plan,
)
from .service import ConnectorError, ConnectorService
from .persistence import SQLiteStateStore
from .recording import JsonlRecorder
from .integration import integration_manifest


def create_app(
    service: Optional[ConnectorService] = None,
    settings: Optional[ConnectorSettings] = None,
    session_manager: Optional[MavlinkSessionManager] = None,
) -> FastAPI:
    settings = settings or ConnectorSettings()
    recorder = JsonlRecorder(settings.record_path) if settings.record_path else None
    owns_service = service is None
    metrics = service.metrics if service is not None else RuntimeMetrics()
    if owns_service:
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
                metrics=metrics,
            )
            if settings.backend == "flight-blender"
            else InMemoryBackend()
        )
        altitude_converter = None
        if settings.altitude_geoid_grid_path:
            try:
                altitude_converter = AltitudeConverter(settings.altitude_geoid_grid_path)
            except AltitudeConversionError as exc:
                raise ValueError(f"invalid altitude_geoid_grid_path: {exc}") from exc
        service = ConnectorService(
            backend,
            SQLiteStateStore(settings.state_db_path),
            recorder=recorder,
            event_history_limit=settings.event_history_limit,
            altitude_converter=altitude_converter,
            telemetry_publish_interval_s=settings.telemetry_publish_interval_s,
            event_coalesce_interval_s=settings.event_coalesce_interval_s,
            metrics=metrics,
        )
    if session_manager is None:
        session_factory = MavlinkVehicleSession.connect
        if recorder is not None:
            def recorded_session_factory(vehicle_id: str, connection_uri: str):
                return MavlinkVehicleSession.connect(
                    vehicle_id,
                    connection_uri,
                    recorder=recorder,
                )

            session_factory = recorded_session_factory
        manager = MavlinkSessionManager(
            settings.mavlink_connections,
            service.ingest_vehicle_snapshot,
            poll_interval_s=settings.mavlink_poll_interval_s,
            reconnect_interval_s=settings.mavlink_reconnect_interval_s,
            session_factory=session_factory,
            on_mission=service.ingest_onboard_mission,
            on_error=lambda vehicle_id, error: service.record_event(
                "MAVLINK_SESSION_ERROR",
                vehicle_id=vehicle_id,
                severity="ERROR",
                details={"error": str(error)},
            ),
        )
    else:
        manager = session_manager
    demo_publisher = None
    if settings.demo_mode:
        if settings.backend != "in-memory":
            raise ValueError("demo_mode requires the in-memory backend")
        if settings.demo_vehicle_id in {connection.vehicle_id for connection in manager.connections}:
            raise ValueError("demo_vehicle_id must differ from configured MAVLink vehicle IDs")
        demo_publisher = DemoVehiclePublisher(
            service,
            settings.demo_vehicle_id,
            interval_s=settings.demo_interval_s,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.start()
        if demo_publisher is not None:
            demo_publisher.start()
        try:
            yield
        finally:
            if demo_publisher is not None:
                demo_publisher.stop()
            manager.stop()
            close_backend = getattr(service.backend, "close", None)
            if close_backend is not None:
                close_backend()
            if recorder is not None:
                recorder.close()
            if owns_service:
                close_state_store = getattr(service.state_store, "close", None)
                if close_state_store is not None:
                    close_state_store()

    app = FastAPI(title="UTM Operations Connector", version="0.1.0", lifespan=lifespan)
    app.state.connector_service = service
    app.state.mavlink_session_manager = manager
    app.state.demo_vehicle_publisher = demo_publisher

    @app.get("/v1/capabilities", response_model=dict)
    def capabilities() -> dict:
        return {
            "backend": service.backend.name,
            "demo_mode": settings.demo_mode,
            "mission_formats": ["canonical", "qgroundcontrol", "mission-planner"],
            "mission_commands": list(NAVIGABLE_MISSION_COMMANDS_INFO),
            "integration_manifest": "/v1/integration",
            "recording": {
                "configured": recorder is not None,
                "mavlink_raw": recorder is not None,
            },
            "mavlink": {
                "configured": bool(manager.connections),
                "non_commanding": True,
                "read_only": True,
                "mission_download": True,
                "recommended_topology": "single_router_endpoint",
                "telemetry_publish_interval_s": settings.telemetry_publish_interval_s,
                "reconnect_interval_s": settings.mavlink_reconnect_interval_s,
                "event_coalesce_interval_s": settings.event_coalesce_interval_s,
            },
            "altitude": {
                "geoid_conversion_configured": settings.altitude_geoid_grid_path is not None,
                "geoid_grid_path": settings.altitude_geoid_grid_path,
                "source_mavlink_global_position": "AMSL",
                "provider_requirement": "WGS84" if service.backend.required_altitude_datum else None,
            },
            "mission_window": service.backend.mission_window_constraints(),
            "operator_commands": [command.value for command in OperationCommand],
        }

    @app.get("/v1/integration", response_model=dict)
    def integration() -> dict:
        """Expose the zero-fork GCS/connector boundary for local discovery."""

        return integration_manifest()

    @app.get("/v1/metrics", response_model=dict)
    def metrics_endpoint() -> dict:
        """Expose process-local diagnostics for GCS and support tooling."""

        active_operations = sum(
            operation.state.declaration in {
                DeclarationState.SUBMITTED,
                DeclarationState.ACCEPTED,
            }
            for operation in service.operations.values()
        )
        snapshot = metrics.snapshot()
        snapshot.update(
            {
                "vehicles": {
                    "active": len(set(service.vehicles) | set(service.vehicle_snapshots)),
                    "configured": len(manager.connections),
                    "session_errors": len(manager.last_errors),
                },
                "operations": {
                    "active": active_operations,
                    "known": len(service.operations),
                },
            }
        )
        return snapshot

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="degraded" if manager.last_errors or service.last_backend_error else "ok",
            active_vehicles=len(set(service.vehicles) | set(service.vehicle_snapshots)),
            active_operations=sum(
                operation.state.declaration in {
                    DeclarationState.SUBMITTED,
                    DeclarationState.ACCEPTED,
                }
                for operation in service.operations.values()
            ),
            backend=service.backend.name,
            backend_error=service.last_backend_error,
        )

    @app.get("/v1/vehicles", response_model=List[dict])
    def vehicles() -> List[dict]:
        configured_vehicle_ids = {connection.vehicle_id for connection in manager.connections}
        vehicle_ids = sorted(
            configured_vehicle_ids | set(service.vehicles) | set(service.vehicle_snapshots)
        )
        active_declarations = {DeclarationState.SUBMITTED, DeclarationState.ACCEPTED}
        result = []
        for vehicle_id in vehicle_ids:
            telemetry = service.vehicles.get(vehicle_id)
            snapshot = service.vehicle_snapshots.get(vehicle_id)
            operations = [
                operation
                for operation in service.operations.values()
                if operation.vehicle_id == vehicle_id
            ]
            result.append(
                {
                    "vehicle_id": vehicle_id,
                    "connection_state": (
                        snapshot.connection_state.value if snapshot else "UNKNOWN"
                    ),
                    "quality": (
                        snapshot.quality.value
                        if snapshot
                        else telemetry.quality.value if telemetry else "UNKNOWN"
                    ),
                    "mavlink_system_id": (
                        snapshot.identity.mavlink_system_id if snapshot else None
                    ),
                    "latest_telemetry_at": (
                        telemetry.observed_at.isoformat() if telemetry else None
                    ),
                    "active_operation_count": sum(
                        operation.state.declaration in active_declarations
                        for operation in operations
                    ),
                    "last_error": manager.last_errors.get(vehicle_id),
                }
            )
        return result

    @app.put("/v1/missions/{vehicle_id}", response_model=dict)
    def put_mission(vehicle_id: str, mission: Mission) -> dict:
        try:
            snapshot = service.put_mission(vehicle_id, mission)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return snapshot.model_dump(mode="json")

    @app.get("/v1/missions/{vehicle_id}", response_model=dict)
    def get_mission(vehicle_id: str) -> dict:
        snapshot = service.missions.get(vehicle_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="mission not found")
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

    @app.put("/v1/missions/{vehicle_id}/mission-planner", response_model=dict)
    def put_mission_planner_mission(
        vehicle_id: str, request: MissionPlannerMissionRequest
    ) -> dict:
        """Normalize a Mission Planner QGC WPL export with explicit UTM metadata."""

        try:
            mission = parse_mission_planner_waypoints(
                request.text,
                vehicle_id=vehicle_id,
                valid_from=request.valid_from,
                valid_until=request.valid_until,
                corridor_radius_m=request.corridor_radius_m,
            )
            return service.put_mission(vehicle_id, mission).model_dump(mode="json")
        except (ConnectorError, MissionParseError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid Mission Planner mission: {exc}") from exc

    @app.put("/v1/vehicles/{vehicle_id}/onboard-mission", response_model=dict)
    def put_onboard_mission(vehicle_id: str, mission: Mission) -> dict:
        try:
            return service.put_onboard_mission(vehicle_id, mission).model_dump(mode="json")
        except ConnectorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/vehicles/{vehicle_id}/onboard-mission", response_model=dict)
    def get_onboard_mission(vehicle_id: str) -> dict:
        snapshot = service.onboard_missions.get(vehicle_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="onboard mission not found")
        return snapshot.model_dump(mode="json")

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
            service.record_backend_error(exc)
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
            service.record_backend_error(exc)
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
            service.record_backend_error(exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ConnectorError as exc:
            status_code = 404 if str(exc) == "operation not found" else 409
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @app.get("/v1/vehicles/{vehicle_id}/status", response_model=dict)
    def vehicle_status(vehicle_id: str) -> dict:
        telemetry = service.vehicles.get(vehicle_id)
        vehicle_snapshot = service.vehicle_snapshots.get(vehicle_id)
        configured = any(connection.vehicle_id == vehicle_id for connection in manager.connections)
        if telemetry is None and vehicle_snapshot is None and not configured:
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
            "last_error": manager.last_errors.get(vehicle_id),
        }

    @app.get("/v1/events", response_model=List[Event])
    def events(limit: int = Query(default=100, ge=1, le=1000)) -> List[Event]:
        return list(reversed(service.events[-limit:]))

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Make the normal local launch URL open the operator workflow."""

        return RedirectResponse(url="/ui/")

    ui_directory = Path(__file__).with_name("ui")
    app.mount("/ui", StaticFiles(directory=ui_directory, html=True), name="ui")

    return app
