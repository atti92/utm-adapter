"""Portable JSONL recording and replay helpers for connector diagnostics."""

from __future__ import annotations

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
