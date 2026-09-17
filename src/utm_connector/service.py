from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from .backends import BackendError, UTMBackend
from .conformance import assess_conformance
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
from .mission_reader import MavlinkMissionRead
from .persistence import SQLiteStateStore
from .recording import JsonlRecorder


class ConnectorError(ValueError):
    pass


class ConnectorService:
    def __init__(
        self,
        backend: UTMBackend,
        state_store: Optional[SQLiteStateStore] = None,
        recorder: Optional[JsonlRecorder] = None,
        event_history_limit: int = 1000,
    ) -> None:
        if event_history_limit < 1:
            raise ValueError("event_history_limit must be greater than zero")
        self.backend = backend
        self.state_store = state_store
        self.recorder = recorder
        self.event_history_limit = event_history_limit
        self.missions: Dict[str, MissionSnapshot] = {}
        self.onboard_missions: Dict[str, MissionSnapshot] = {}
        self.onboard_mission_reads: Dict[str, MavlinkMissionRead] = {}
        self.mission_drifts: Dict[str, MissionDriftReport] = {}
        self.vehicles: Dict[str, VehicleTelemetry] = {}
        self.vehicle_snapshots: Dict[str, VehicleStateSnapshot] = {}
        self.operations: Dict[UUID, Operation] = {}
        self.events: List[Event] = []
        if state_store is not None:
            self.missions = state_store.load_missions(kind="submitted")
            self.onboard_missions = state_store.load_missions(kind="onboard")
            self.vehicles = state_store.load_telemetry()
            self.vehicle_snapshots = state_store.load_vehicle_snapshots()
            self.operations = state_store.load_operations()
            register_operation = getattr(self.backend, "register_operation", None)
            if register_operation is not None:
                for operation in self.operations.values():
                    register_operation(operation)
            self.events = state_store.load_events(limit=event_history_limit)
            for vehicle_id, submitted in self.missions.items():
                onboard = self.onboard_missions.get(vehicle_id)
                if onboard is not None:
                    self.mission_drifts[vehicle_id] = compare_missions(submitted.mission, onboard.mission)

    def _event(self, event_type: str, *, intent: Optional[OperationIntent] = None, **kwargs: object) -> None:
        event = Event(
            event_type=event_type,
            correlation_id=intent.correlation_id if intent else None,
            **kwargs,
        )
        self.events.append(event)
        if len(self.events) > self.event_history_limit:
            del self.events[: len(self.events) - self.event_history_limit]
        if self.state_store is not None:
            self.state_store.append_event(event)
        if self.recorder is not None:
            self.recorder.record("connector_event", event.model_dump(mode="json"))

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
        if self.state_store is not None:
            self.state_store.save_mission(vehicle_id, snapshot, kind="submitted")
        self._event("MISSION_UPDATED", vehicle_id=vehicle_id, details={"mission_hash": snapshot.mission_hash})
        onboard_read = self.onboard_mission_reads.get(vehicle_id)
        if onboard_read is not None:
            self._record_onboard_mission(vehicle_id, onboard_read)
        return snapshot

    def put_onboard_mission(self, vehicle_id: str, mission: Mission) -> MissionDriftReport:
        if mission.vehicle_id != vehicle_id:
            raise ConnectorError("onboard mission vehicle_id does not match path")
        submitted = self.missions.get(vehicle_id)
        if submitted is None:
            raise ConnectorError("mission not found for vehicle")

        current = MissionSnapshot(mission=mission, mission_hash=mission.canonical_hash())
        if self.state_store is not None:
            self.state_store.save_mission(vehicle_id, current, kind="onboard")
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

    def ingest_onboard_mission(self, onboard_read: MavlinkMissionRead) -> Optional[MissionDriftReport]:
        self.onboard_mission_reads[onboard_read.vehicle_id] = onboard_read
        if onboard_read.vehicle_id not in self.missions:
            self._event(
                "ONBOARD_MISSION_RECEIVED_WITHOUT_SUBMISSION",
                vehicle_id=onboard_read.vehicle_id,
                severity="WARNING",
                details={"mission_count": onboard_read.mission_count},
            )
            return None
        return self._record_onboard_mission(onboard_read.vehicle_id, onboard_read)

    def _record_onboard_mission(self, vehicle_id: str, onboard_read: MavlinkMissionRead) -> MissionDriftReport:
        submitted = self.missions[vehicle_id]
        current = onboard_read.to_mission(submitted.mission)
        snapshot = MissionSnapshot(mission=current, mission_hash=current.canonical_hash())
        report = compare_missions(submitted.mission, current)
        self.onboard_missions[vehicle_id] = snapshot
        self.mission_drifts[vehicle_id] = report
        if self.state_store is not None:
            self.state_store.save_mission(vehicle_id, snapshot, kind="onboard")
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
        if self.state_store is not None:
            self.state_store.save_telemetry(telemetry)
        active_operations = [
            operation
            for operation in self.operations.values()
            if operation.vehicle_id == vehicle_id
            and operation.state.telemetry_publication == TelemetryPublicationState.ACTIVE
        ]
        publication_errors: Dict[UUID, BackendError] = {}
        for operation in active_operations:
            try:
                self.backend.publish_telemetry(telemetry, operation)
            except BackendError as exc:
                publication_errors[operation.operation_id] = exc

        for operation in active_operations:
            mission_snapshot = self.missions.get(vehicle_id)
            if mission_snapshot is not None:
                assessment = assess_conformance(mission_snapshot.mission, telemetry)
                operation.state.conformance = assessment.state
                self._event(
                    "CONFORMANCE_ASSESSED",
                    vehicle_id=vehicle_id,
                    operation_id=operation.operation_id,
                    severity="WARNING" if assessment.state in {
                        ConformanceState.NEAR_BOUNDARY,
                        ConformanceState.NON_CONFORMING,
                        ConformanceState.TELEMETRY_UNRELIABLE,
                    } else "INFO",
                    details=assessment.model_dump(mode="json"),
                )
            publication_error = publication_errors.get(operation.operation_id)
            operation.state.telemetry_publication = (
                TelemetryPublicationState.FAILED
                if publication_error is not None
                else TelemetryPublicationState.ACTIVE
            )
            operation.updated_at = datetime.now(timezone.utc)
            if self.state_store is not None:
                self.state_store.save_operation(operation)

        if publication_errors:
            for operation in active_operations:
                publication_error = publication_errors.get(operation.operation_id)
                if publication_error is not None:
                    self._event(
                        "TELEMETRY_PUBLICATION_FAILED",
                        vehicle_id=vehicle_id,
                        operation_id=operation.operation_id,
                        severity="ERROR",
                        details={
                            "provider_operation_id": operation.provider_operation_id,
                            "error": str(publication_error),
                        },
                    )
            raise next(iter(publication_errors.values()))
        self._event(
            "TELEMETRY_PUBLISHED" if active_operations else "TELEMETRY_RECEIVED",
            vehicle_id=vehicle_id,
            details={"quality": telemetry.quality},
        )
        return telemetry

    def ingest_vehicle_snapshot(self, snapshot: VehicleStateSnapshot) -> VehicleStateSnapshot:
        vehicle_id = snapshot.identity.connector_vehicle_id
        self.vehicle_snapshots[vehicle_id] = snapshot
        if self.state_store is not None:
            self.state_store.save_vehicle_snapshot(snapshot)
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

        candidate = operation.model_copy(deep=True)
        state = candidate.state
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
            state.declaration = DeclarationState.COMPLETED
            state.telemetry_publication = TelemetryPublicationState.STOPPED
        else:
            raise ConnectorError("unsupported command for existing operation")

        candidate = self.backend.update_operation(candidate, intent.command)
        candidate.updated_at = datetime.now(timezone.utc)
        self.operations[candidate.operation_id] = candidate
        if self.state_store is not None:
            self.state_store.save_operation(candidate)
        self._event(
            "OPERATION_STATE_CHANGED",
            intent=intent,
            vehicle_id=candidate.vehicle_id,
            operation_id=candidate.operation_id,
            details={"command": intent.command.value, "state": state.model_dump(mode="json")},
        )
        return candidate

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
        operation = self.backend.submit_operation(operation, snapshot.mission)
        self.operations[operation.operation_id] = operation
        if self.state_store is not None:
            self.state_store.save_operation(operation)
        self._event(
            "OPERATION_SUBMITTED",
            intent=intent,
            vehicle_id=vehicle_id,
            operation_id=operation.operation_id,
            details={"mission_hash": operation.mission_hash},
        )
        return operation

    def refresh_operation(self, operation_id: UUID) -> Operation:
        """Reconcile one operation with provider-owned state."""

        operation = self.operations.get(operation_id)
        if operation is None:
            raise ConnectorError("operation not found")
        fetch_operation = getattr(self.backend, "fetch_operation", None)
        if fetch_operation is None:
            raise ConnectorError("backend does not support operation refresh")
        provider = fetch_operation(operation)
        provider_state = provider.get("state")
        if not isinstance(provider_state, int):
            raise ConnectorError("provider operation response did not include an integer state")

        candidate = operation.model_copy(deep=True)
        if provider_state == 8:
            candidate.state.declaration = DeclarationState.REJECTED
        elif provider_state in (6, 7):
            candidate.state.declaration = DeclarationState.CANCELLED
            candidate.state.telemetry_publication = TelemetryPublicationState.STOPPED
        elif provider_state == 5:
            candidate.state.declaration = DeclarationState.COMPLETED
            candidate.state.telemetry_publication = TelemetryPublicationState.STOPPED
        elif provider_state in (1, 2, 3, 4):
            candidate.state.declaration = DeclarationState.ACCEPTED
        else:
            candidate.state.declaration = DeclarationState.SUBMITTED
        approved = provider.get("is_approved")
        if isinstance(approved, bool) or isinstance(approved, int):
            candidate.state.authorization = (
                AuthorizationState.AUTHORIZED if bool(approved) else AuthorizationState.PENDING
            )
        if provider_state == 3:
            candidate.state.conformance = ConformanceState.NON_CONFORMING
        candidate.updated_at = datetime.now(timezone.utc)
        self.operations[operation_id] = candidate
        if self.state_store is not None:
            self.state_store.save_operation(candidate)
        self._event(
            "OPERATION_REFRESHED",
            vehicle_id=candidate.vehicle_id,
            operation_id=candidate.operation_id,
            details={"provider_state": provider_state, "provider": provider},
        )
        return candidate
