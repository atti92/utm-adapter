from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .backends import BackendError, FlightBlenderBackend, InMemoryBackend
from .altitude import AltitudeConversionError, AltitudeConverter
from .config import ConnectorSettings
from .credentials import resolve_client_secret
from .demo import DemoVehiclePublisher
from .domain import (
    DeclarationState,
    Event,
    HealthResponse,
    Mission,
    MissionPlannerMissionRequest,
    OnboardMissionImportRequest,
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
        flight_blender_client_secret = (
            resolve_client_secret(
                client_secret=settings.flight_blender_client_secret,
                keyring_service=settings.flight_blender_client_secret_keyring_service,
                keyring_account=settings.flight_blender_client_secret_keyring_account,
            )
            if settings.backend == "flight-blender"
            else settings.flight_blender_client_secret
        )
        backend = (
            FlightBlenderBackend(
                settings.flight_blender_base_url,
                bearer_token=settings.flight_blender_bearer_token,
                oauth_token_url=settings.flight_blender_token_url,
                oauth_client_id=settings.flight_blender_client_id,
                oauth_client_secret=flight_blender_client_secret,
                oauth_scope=settings.flight_blender_scope,
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

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        """Make every GCS request traceable without changing API payloads."""

        incoming = request.headers.get("X-Correlation-ID")
        try:
            correlation_id = str(UUID(incoming)) if incoming else str(uuid4())
        except ValueError:
            correlation_id = str(uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    app.state.demo_vehicle_publisher = demo_publisher

    @app.get("/v1/capabilities", response_model=dict)
    def capabilities() -> dict:
        return {
            "backend": service.backend.name,
            "demo_mode": settings.demo_mode,
            "demo_route": DemoVehiclePublisher.route_coordinates() if settings.demo_mode else None,
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
            "provider_authentication": {
                "mode": getattr(service.backend, "authentication_mode", "none"),
                "secret_material_exposed": False,
            },
            "operator_commands": [command.value for command in OperationCommand],
        }

    @app.get("/v1/integration", response_model=dict)
    def integration() -> dict:
        """Expose the zero-fork GCS/connector boundary for local discovery."""

        return integration_manifest()

    @app.get("/v1/metrics", response_model=dict)
    def metrics_endpoint() -> dict:
        """Expose process-local diagnostics for GCS and support tooling."""

        vehicle_ids = sorted(
            set(service.vehicles)
            | set(service.vehicle_snapshots)
            | {connection.vehicle_id for connection in manager.connections}
        )
        active_operations = sum(
            operation.state.declaration in {
                DeclarationState.SUBMITTED,
                DeclarationState.ACCEPTED,
            }
            for operation in service.operations.values()
        )
        now = datetime.now(timezone.utc)
        vehicle_diagnostics = []
        for vehicle_id in vehicle_ids:
            telemetry = service.vehicles.get(vehicle_id)
            snapshot_for_vehicle = service.vehicle_snapshots.get(vehicle_id)
            drift = service.mission_drifts.get(vehicle_id)
            telemetry_age_s = None
            if telemetry is not None:
                telemetry_age_s = round(
                    max(0.0, (now - telemetry.observed_at).total_seconds()), 3
                )
            vehicle_diagnostics.append(
                {
                    "vehicle_id": vehicle_id,
                    "connection_state": (
                        snapshot_for_vehicle.connection_state.value
                        if snapshot_for_vehicle
                        else "UNKNOWN"
                    ),
                    "quality": (
                        snapshot_for_vehicle.quality.value
                        if snapshot_for_vehicle
                        else telemetry.quality.value if telemetry else "UNKNOWN"
                    ),
                    "heartbeat_age_s": (
                        snapshot_for_vehicle.health.heartbeat_age_s
                        if snapshot_for_vehicle
                        else None
                    ),
                    "position_age_s": (
                        snapshot_for_vehicle.health.position_age_s
                        if snapshot_for_vehicle
                        else telemetry_age_s
                    ),
                    "telemetry_age_s": telemetry_age_s,
                    "last_telemetry_at": (
                        telemetry.observed_at.isoformat() if telemetry else None
                    ),
                    "mission_drift": drift.classification.value if drift else None,
                    "mission_hash_mismatch": bool(
                        drift and drift.classification.value != "NO_CHANGE"
                    ),
                }
            )
        active_operation_states = [
            {
                "operation_id": str(operation.operation_id),
                "vehicle_id": operation.vehicle_id,
                "declaration": operation.state.declaration.value,
                "authorization": operation.state.authorization.value,
                "telemetry_publication": operation.state.telemetry_publication.value,
                "conformance": operation.state.conformance.value,
            }
            for operation in service.operations.values()
            if operation.state.declaration
            in {DeclarationState.SUBMITTED, DeclarationState.ACCEPTED}
        ]
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
                    "active_states": active_operation_states,
                },
                "vehicle_diagnostics": vehicle_diagnostics,
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

    @app.get("/v1/vehicles/{vehicle_id}/onboard-mission/raw", response_model=dict)
    def get_raw_onboard_mission(vehicle_id: str) -> dict:
        """Return the latest raw MAVLink route before UTM metadata is applied."""

        onboard_read = service.onboard_mission_reads.get(vehicle_id)
        if onboard_read is None:
            raise HTTPException(status_code=404, detail="raw onboard mission not found")
        return {
            "vehicle_id": onboard_read.vehicle_id,
            "mission_count": onboard_read.mission_count,
            "received_at": onboard_read.received_at.isoformat(),
            "waypoints": [waypoint.model_dump(mode="json") for waypoint in onboard_read.waypoints],
        }

    @app.post("/v1/vehicles/{vehicle_id}/onboard-mission/import", response_model=dict)
    def import_onboard_mission(
        vehicle_id: str, request: OnboardMissionImportRequest
    ) -> dict:
        """Import a downloaded vehicle route with explicit UTM metadata."""

        try:
            return service.import_onboard_mission(
                vehicle_id,
                valid_from=request.valid_from,
                valid_until=request.valid_until,
                corridor_radius_m=request.corridor_radius_m,
            ).model_dump(mode="json")
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
