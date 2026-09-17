"""Small SQLite state store for the local connector runtime."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Dict, List
from uuid import UUID

from .domain import Event, MissionSnapshot, Operation, VehicleStateSnapshot, VehicleTelemetry


class SQLiteStateStore:
    """Persist connector state without coupling the domain to SQLite."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        self._closed = False
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    vehicle_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (vehicle_id, kind)
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS telemetry (
                    vehicle_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vehicle_snapshots (
                    vehicle_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )

    def save_mission(self, vehicle_id: str, snapshot: MissionSnapshot, *, kind: str) -> None:
        if kind not in {"submitted", "onboard"}:
            raise ValueError("mission kind must be submitted or onboard")
        self._upsert("missions", (vehicle_id, kind, snapshot.model_dump_json()))

    def load_missions(self, *, kind: str) -> Dict[str, MissionSnapshot]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT vehicle_id, payload FROM missions WHERE kind = ?",
                (kind,),
            ).fetchall()
        return {vehicle_id: MissionSnapshot.model_validate_json(payload) for vehicle_id, payload in rows}

    def save_operation(self, operation: Operation) -> None:
        self._upsert("operations", (str(operation.operation_id), operation.model_dump_json()))

    def load_operations(self) -> Dict[UUID, Operation]:
        with self._lock:
            rows = self._connection.execute("SELECT operation_id, payload FROM operations").fetchall()
        return {UUID(operation_id): Operation.model_validate_json(payload) for operation_id, payload in rows}

    def save_telemetry(self, telemetry: VehicleTelemetry) -> None:
        self._upsert("telemetry", (telemetry.vehicle_id, telemetry.model_dump_json()))

    def load_telemetry(self) -> Dict[str, VehicleTelemetry]:
        with self._lock:
            rows = self._connection.execute("SELECT vehicle_id, payload FROM telemetry").fetchall()
        return {vehicle_id: VehicleTelemetry.model_validate_json(payload) for vehicle_id, payload in rows}

    def save_vehicle_snapshot(self, snapshot: VehicleStateSnapshot) -> None:
        self._upsert(
            "vehicle_snapshots",
            (snapshot.identity.connector_vehicle_id, snapshot.model_dump_json()),
        )

    def load_vehicle_snapshots(self) -> Dict[str, VehicleStateSnapshot]:
        with self._lock:
            rows = self._connection.execute("SELECT vehicle_id, payload FROM vehicle_snapshots").fetchall()
        return {
            vehicle_id: VehicleStateSnapshot.model_validate_json(payload)
            for vehicle_id, payload in rows
        }

    def append_event(self, event: Event) -> None:
        self._upsert(
            "events",
            (str(event.event_id), event.timestamp.isoformat(), event.model_dump_json()),
        )

    def load_events(self, *, limit: int | None = None) -> List[Event]:
        if limit is not None and limit < 1:
            raise ValueError("event history limit must be greater than zero")
        with self._lock:
            if limit is None:
                rows = self._connection.execute(
                    "SELECT payload FROM events ORDER BY timestamp, event_id"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT payload FROM events ORDER BY timestamp DESC, event_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                rows.reverse()
        return [Event.model_validate_json(payload) for (payload,) in rows]

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def _upsert(self, table: str, values: tuple[str, ...]) -> None:
        statements = {
            "missions": (
                "INSERT INTO missions(vehicle_id, kind, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(vehicle_id, kind) DO UPDATE SET payload = excluded.payload"
            ),
            "operations": (
                "INSERT INTO operations(operation_id, payload) VALUES (?, ?) "
                "ON CONFLICT(operation_id) DO UPDATE SET payload = excluded.payload"
            ),
            "telemetry": (
                "INSERT INTO telemetry(vehicle_id, payload) VALUES (?, ?) "
                "ON CONFLICT(vehicle_id) DO UPDATE SET payload = excluded.payload"
            ),
            "vehicle_snapshots": (
                "INSERT INTO vehicle_snapshots(vehicle_id, payload) VALUES (?, ?) "
                "ON CONFLICT(vehicle_id) DO UPDATE SET payload = excluded.payload"
            ),
            "events": "INSERT OR IGNORE INTO events(event_id, timestamp, payload) VALUES (?, ?, ?)",
        }
        try:
            statement = statements[table]
        except KeyError as exc:
            raise ValueError(f"unsupported persistence table: {table}") from exc
        with self._lock, self._connection:
            self._connection.execute(statement, values)
