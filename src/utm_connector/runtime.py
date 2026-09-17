"""Runtime orchestration for configured, read-only MAVLink sessions."""

from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional, Protocol

from .config import MavlinkConnectionConfig
from .domain import VehicleStateSnapshot
from .mavlink import MavlinkVehicleSession
from .mission_reader import MavlinkMissionRead


class PollableSession(Protocol):
    def poll(self, timeout: float = 0.0) -> object:
        ...

    def snapshot(self) -> VehicleStateSnapshot:
        ...

    @property
    def onboard_mission(self) -> Optional[MavlinkMissionRead]:
        ...

    def request_mission(self) -> None:
        ...

    def close(self) -> None:
        ...


SessionFactory = Callable[[str, str], PollableSession]
SnapshotHandler = Callable[[VehicleStateSnapshot], None]
MissionHandler = Callable[[MavlinkMissionRead], None]
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
        on_mission: Optional[MissionHandler] = None,
        on_error: Optional[ErrorHandler] = None,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be greater than zero")
        self.connections = connections
        self.on_snapshot = on_snapshot
        self.poll_interval_s = poll_interval_s
        self.session_factory = session_factory
        self.on_mission = on_mission
        self.on_error = on_error
        self.sessions: Dict[str, PollableSession] = {}
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()
        self._delivered_missions: Dict[str, MavlinkMissionRead] = {}

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
        with self._lock:
            threads = list(self._threads)
            sessions = list(self.sessions.values())
            self._stop.set()

        # Closing the underlying transport is important for real pymavlink
        # connections: recv_match() may otherwise keep a worker alive until
        # its socket timeout expires, and a subsequent start() would leak the
        # old connection.
        for session in sessions:
            close = getattr(session, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    # Shutdown must remain best-effort. The worker join below
                    # still gives sessions without a cooperative close method
                    # a bounded opportunity to finish.
                    pass

        for thread in threads:
            thread.join(timeout=max(1.0, self.poll_interval_s * 5))
        with self._lock:
            self._threads = []
            self.sessions.clear()
            self._delivered_missions.clear()

    def request_mission(self, vehicle_id: str) -> None:
        session = self.sessions.get(vehicle_id)
        if session is None:
            raise KeyError(f"MAVLink session not found for vehicle: {vehicle_id}")
        session.request_mission()
        self._delivered_missions.pop(vehicle_id, None)

    def poll_once(self) -> int:
        """Poll all sessions once; useful for deterministic tests and tools."""

        messages = 0
        for vehicle_id, session in list(self.sessions.items()):
            try:
                message = session.poll(timeout=0.0)
                if message is not None:
                    self._deliver(vehicle_id, session)
                    messages += 1
            except Exception as exc:
                self._report_error(vehicle_id, exc)
        return messages

    def _run_session(self, vehicle_id: str, session: PollableSession) -> None:
        while not self._stop.is_set():
            try:
                message = session.poll(timeout=self.poll_interval_s)
                if message is not None:
                    self._deliver(vehicle_id, session)
            except Exception as exc:
                if self._stop.is_set():
                    break
                self._report_error(vehicle_id, exc)
                self._stop.wait(self.poll_interval_s)

    def _report_error(self, vehicle_id: str, error: Exception) -> None:
        if self.on_error:
            self.on_error(vehicle_id, error)

    def _deliver(self, vehicle_id: str, session: PollableSession) -> None:
        self.on_snapshot(session.snapshot())
        mission = getattr(session, "onboard_mission", None)
        if mission is not None and mission is not self._delivered_missions.get(vehicle_id):
            self._delivered_missions[vehicle_id] = mission
            if self.on_mission:
                self.on_mission(mission)
