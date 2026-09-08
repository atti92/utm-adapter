"""Runtime orchestration for configured, read-only MAVLink sessions."""

from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional, Protocol

from .config import MavlinkConnectionConfig
from .domain import VehicleStateSnapshot
from .mavlink import MavlinkVehicleSession


class PollableSession(Protocol):
    def poll(self, timeout: float = 0.0) -> object:
        ...

    def snapshot(self) -> VehicleStateSnapshot:
        ...


SessionFactory = Callable[[str, str], PollableSession]
SnapshotHandler = Callable[[VehicleStateSnapshot], None]
ErrorHandler = Callable[[str, Exception], None]


class MavlinkSessionManager:
    """Own configured sessions and publish snapshots from background threads."""

    def __init__(
        self,
        connections: List[MavlinkConnectionConfig],
        on_snapshot: SnapshotHandler,
        *,
        poll_interval_s: float = 0.2,
        session_factory: SessionFactory = MavlinkVehicleSession.connect,
        on_error: Optional[ErrorHandler] = None,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be greater than zero")
        self.connections = connections
        self.on_snapshot = on_snapshot
        self.poll_interval_s = poll_interval_s
        self.session_factory = session_factory
        self.on_error = on_error
        self.sessions: Dict[str, PollableSession] = {}
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._threads:
                return
            self._stop.clear()
            for connection in self.connections:
                try:
                    session = self.session_factory(connection.vehicle_id, connection.connection_uri)
                except Exception as exc:
                    self._report_error(connection.vehicle_id, exc)
                    continue
                self.sessions[connection.vehicle_id] = session
                thread = threading.Thread(
                    target=self._run_session,
                    args=(connection.vehicle_id, session),
                    name=f"mavlink-{connection.vehicle_id}",
                    daemon=True,
                )
                self._threads.append(thread)
                thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=max(1.0, self.poll_interval_s * 5))
        self._threads = []

    def poll_once(self) -> int:
        """Poll all sessions once; useful for deterministic tests and tools."""

        messages = 0
        for vehicle_id, session in list(self.sessions.items()):
            try:
                message = session.poll(timeout=0.0)
                if message is not None:
                    self.on_snapshot(session.snapshot())
                    messages += 1
            except Exception as exc:
                self._report_error(vehicle_id, exc)
        return messages

    def _run_session(self, vehicle_id: str, session: PollableSession) -> None:
        while not self._stop.is_set():
            try:
                message = session.poll(timeout=self.poll_interval_s)
                if message is not None:
                    self.on_snapshot(session.snapshot())
            except Exception as exc:
                self._report_error(vehicle_id, exc)
                self._stop.wait(self.poll_interval_s)

    def _report_error(self, vehicle_id: str, error: Exception) -> None:
        if self.on_error:
            self.on_error(vehicle_id, error)
