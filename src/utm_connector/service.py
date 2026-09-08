from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from .backends import UTMBackend
from .domain import (
    AuthorizationState,
    ConformanceState,
    DeclarationState,
    Event,
    Mission,
    MissionSnapshot,
    MissionDriftReport,
    Operation,
    OperationCommand,
    OperationIntent,
    OperationState,
    TelemetryPublicationState,
    VehicleStateSnapshot,
    VehicleTelemetry,
)
from .drift import compare_missions


class ConnectorError(ValueError):
    pass


class ConnectorService:
    def __init__(self, backend: UTMBackend) -> None:
        self.backend = backend
        self.missions: Dict[str, MissionSnapshot] = {}
        self.onboard_missions: Dict[str, MissionSnapshot] = {}
        self.mission_drifts: Dict[str, MissionDriftReport] = {}
        self.vehicles: Dict[str, VehicleTelemetry] = {}
        self.vehicle_snapshots: Dict[str, VehicleStateSnapshot] = {}
        self.operations: Dict[UUID, Operation] = {}
        self.events: List[Event] = []

    def _event(self, event_type: str, *, intent: Optional[OperationIntent] = None, **kwargs: object) -> None:
        self.events.append(
            Event(
                event_type=event_type,
                correlation_id=intent.correlation_id if intent else None,
                **kwargs,
            )
        )

    def record_event(
        self,
        event_type: str,
        *,
        vehicle_id: Optional[str] = None,
        severity: str = "INFO",
        details: Optional[Dict[str, object]] = None,
    ) -> None:
        self._event(
            event_type,
            vehicle_id=vehicle_id,
            severity=severity,
            details=details or {},
        )

    def put_mission(self, vehicle_id: str, mission: Mission) -> MissionSnapshot:
        if mission.vehicle_id != vehicle_id:
            raise ConnectorError("mission vehicle_id does not match path")
        snapshot = MissionSnapshot(mission=mission, mission_hash=mission.canonical_hash())
        self.missions[vehicle_id] = snapshot
        self._event("MISSION_UPDATED", vehicle_id=vehicle_id, details={"mission_hash": snapshot.mission_hash})
        return snapshot

    def put_onboard_mission(self, vehicle_id: str, mission: Mission) -> MissionDriftReport:
        if mission.vehicle_id != vehicle_id:
            raise ConnectorError("onboard mission vehicle_id does not match path")
        submitted = self.missions.get(vehicle_id)
        if submitted is None:
            raise ConnectorError("mission not found for vehicle")

        current = MissionSnapshot(mission=mission, mission_hash=mission.canonical_hash())
        report = compare_missions(submitted.mission, current.mission)
        self.onboard_missions[vehicle_id] = current
        self.mission_drifts[vehicle_id] = report
        self._event(
            "MISSION_DRIFT_CHECKED",
            vehicle_id=vehicle_id,
            severity="WARNING" if report.classification.value != "NO_CHANGE" else "INFO",
            details=report.model_dump(mode="json"),
        )
        return report

    def put_telemetry(self, vehicle_id: str, telemetry: VehicleTelemetry) -> VehicleTelemetry:
        if telemetry.vehicle_id != vehicle_id:
            raise ConnectorError("telemetry vehicle_id does not match path")
        self.vehicles[vehicle_id] = telemetry
        self.backend.publish_telemetry(telemetry)
        for operation in self.operations.values():
            if operation.vehicle_id == vehicle_id and operation.state.telemetry_publication == TelemetryPublicationState.ACTIVE:
                operation.state.telemetry_publication = TelemetryPublicationState.ACTIVE
                operation.updated_at = datetime.now(timezone.utc)
        self._event("TELEMETRY_PUBLISHED", vehicle_id=vehicle_id, details={"quality": telemetry.quality})
        return telemetry

    def ingest_vehicle_snapshot(self, snapshot: VehicleStateSnapshot) -> VehicleStateSnapshot:
        vehicle_id = snapshot.identity.connector_vehicle_id
        self.vehicle_snapshots[vehicle_id] = snapshot
        if snapshot.telemetry is not None:
            self.put_telemetry(vehicle_id, snapshot.telemetry)
        self._event(
            "VEHICLE_STATE_UPDATED",
            vehicle_id=vehicle_id,
            details={
                "connection_state": snapshot.connection_state,
                "quality": snapshot.quality,
            },
        )
        return snapshot

    def apply_intent(self, intent: OperationIntent) -> Operation:
        operation = self.operations.get(intent.operation_id)
        if operation is None:
            raise ConnectorError("operation not found")

        state = operation.state
        if intent.command == OperationCommand.START_OPERATION:
            if state.declaration != DeclarationState.ACCEPTED:
                raise ConnectorError("operation must be accepted before it can start")
            if state.authorization not in (AuthorizationState.AUTHORIZED, AuthorizationState.NOT_REQUIRED):
                raise ConnectorError("operation is not authorized")
            state.telemetry_publication = TelemetryPublicationState.ACTIVE
        elif intent.command == OperationCommand.CANCEL_OPERATION:
            if state.declaration == DeclarationState.CANCELLED:
                raise ConnectorError("operation is already cancelled")
            state.declaration = DeclarationState.CANCELLED
            state.telemetry_publication = TelemetryPublicationState.STOPPED
        elif intent.command == OperationCommand.COMPLETE_OPERATION:
            if state.declaration != DeclarationState.ACCEPTED:
                raise ConnectorError("only an accepted operation can be completed")
            state.telemetry_publication = TelemetryPublicationState.STOPPED
        else:
            raise ConnectorError("unsupported command for existing operation")

        operation.updated_at = datetime.now(timezone.utc)
        self.operations[operation.operation_id] = operation
        self._event(
            "OPERATION_STATE_CHANGED",
            intent=intent,
            vehicle_id=operation.vehicle_id,
            operation_id=operation.operation_id,
            details={"command": intent.command.value, "state": state.model_dump(mode="json")},
        )
        return operation

    def submit_operation(self, intent: OperationIntent, vehicle_id: str) -> Operation:
        if intent.command != OperationCommand.SUBMIT_OPERATION:
            raise ConnectorError("new operations require SUBMIT_OPERATION")
        if intent.operation_id in self.operations:
            raise ConnectorError("operation_id is already in use")
        snapshot = self.missions.get(vehicle_id)
        if snapshot is None:
            raise ConnectorError("mission not found for vehicle")
        operation = Operation(
            operation_id=intent.operation_id,
            vehicle_id=vehicle_id,
            mission_id=snapshot.mission.mission_id,
            mission_hash=snapshot.mission_hash,
            state=OperationState(
                declaration=DeclarationState.ACCEPTED,
                authorization=AuthorizationState.AUTHORIZED,
            ),
        )
        self.operations[operation.operation_id] = self.backend.submit_operation(operation)
        self._event(
            "OPERATION_SUBMITTED",
            intent=intent,
            vehicle_id=vehicle_id,
            operation_id=operation.operation_id,
            details={"mission_hash": operation.mission_hash},
        )
        return operation
