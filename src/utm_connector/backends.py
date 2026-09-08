from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from .domain import Operation, VehicleTelemetry


class UTMBackend(ABC):
    name = "backend"

    @abstractmethod
    def submit_operation(self, operation: Operation) -> Operation:
        """Submit an operation and return the provider-normalized result."""

    @abstractmethod
    def publish_telemetry(self, telemetry: VehicleTelemetry) -> None:
        """Publish one canonical telemetry observation."""


class InMemoryBackend(UTMBackend):
    """Deterministic backend used by the local environment and tests."""

    name = "in-memory"

    def __init__(self) -> None:
        self.operations: Dict[str, Operation] = {}
        self.telemetry: List[VehicleTelemetry] = []

    def submit_operation(self, operation: Operation) -> Operation:
        self.operations[str(operation.operation_id)] = operation
        return operation

    def publish_telemetry(self, telemetry: VehicleTelemetry) -> None:
        self.telemetry.append(telemetry)

