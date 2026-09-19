"""Portable JSONL recording and replay helpers for connector diagnostics."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import monotonic_ns
from typing import Any, Callable, Iterator, Mapping


class JsonlRecorder:
    """Append structured records that can be inspected or replayed offline."""

    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._file = open(path, "a", encoding="utf-8")
        self._closed = False

    def record(self, record_type: str, payload: Mapping[str, Any]) -> None:
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": monotonic_ns(),
            "record_type": record_type,
            "payload": dict(payload),
        }
        with self._lock:
            self._file.write(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) + "\n")
            self._file.flush()

    def record_mavlink_frame(
        self,
        vehicle_id: str,
        frame: bytes,
        *,
        received_at: datetime | None = None,
    ) -> None:
        """Record one raw MAVLink wire frame without coupling replay to pymavlink."""

        if not vehicle_id:
            raise ValueError("vehicle_id must not be empty")
        if not isinstance(frame, bytes):
            raise TypeError("MAVLink frame must be bytes")
        payload: dict[str, Any] = {
            "vehicle_id": vehicle_id,
            "frame_b64": base64.b64encode(frame).decode("ascii"),
        }
        if received_at is not None:
            if received_at.tzinfo is None or received_at.utcoffset() is None:
                raise ValueError("received_at must include a timezone")
            payload["received_at"] = received_at.astimezone(timezone.utc).isoformat()
        self.record("mavlink_frame", payload)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._file.close()
                self._closed = True


class JsonlReplay:
    """Replay recorded records through a caller-supplied deterministic handler."""

    def __init__(self, path: str) -> None:
        self.path = path

    def records(self) -> Iterator[dict[str, Any]]:
        with open(self.path, encoding="utf-8") as recorded_file:
            for line_number, line in enumerate(recorded_file, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL record at line {line_number}") from exc
                if not isinstance(record, dict) or not isinstance(record.get("record_type"), str):
                    raise ValueError(f"invalid connector record at line {line_number}")
                yield record

    def replay(self, handler: Callable[[str, dict[str, Any]], None]) -> int:
        count = 0
        for record in self.records():
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("connector record payload must be an object")
            handler(record["record_type"], payload)
            count += 1
        return count

    def mavlink_frames(self) -> Iterator[tuple[str, bytes]]:
        """Yield raw MAVLink frames in their recorded order.

        Non-MAVLink records are ignored so a single connector journal can be
        used for both event diagnostics and wire-level replay.
        """

        for record in self.records():
            if record["record_type"] != "mavlink_frame":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("MAVLink record payload must be an object")
            vehicle_id = payload.get("vehicle_id")
            frame_b64 = payload.get("frame_b64")
            if not isinstance(vehicle_id, str) or not vehicle_id:
                raise ValueError("MAVLink record vehicle_id must be a non-empty string")
            if not isinstance(frame_b64, str):
                raise ValueError("MAVLink record frame_b64 must be a string")
            try:
                frame = base64.b64decode(frame_b64, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError("MAVLink record frame_b64 is not valid base64") from exc
            yield vehicle_id, frame

    def replay_mavlink(self, handler: Callable[[str, bytes], None]) -> int:
        """Replay raw frames through a caller-supplied deterministic handler."""

        count = 0
        for vehicle_id, frame in self.mavlink_frames():
            handler(vehicle_id, frame)
            count += 1
        return count
