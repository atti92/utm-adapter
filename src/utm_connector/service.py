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
    Operation,
    OperationCommand,
    OperationIntent,
    OperationState,
    TelemetryPublicationState,
    VehicleTelemetry,
)


class ConnectorError(ValueError):
    pass


class ConnectorService:
    def __init__(self, backend: UTMBackend) -> None:
        self.backend = backend
        self.missions: Dict[str, MissionSnapshot] = {}
        self.vehicles: Dict[str, VehicleTelemetry] = {}
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

    def put_mission(self, vehicle_id: str, mission: Mission) -> MissionSnapshot:
        if mission.vehicle_id != vehicle_id:
            raise ConnectorError("mission vehicle_id does not match path")
        snapshot = MissionSnapshot(mission=mission, mission_hash=mission.canonical_hash())
        self.missions[vehicle_id] = snapshot
        self._event("MISSION_UPDATED", vehicle_id=vehicle_id, details={"mission_hash": snapshot.mission_hash})
        return snapshot

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
