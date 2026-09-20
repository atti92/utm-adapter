"""Small, thread-safe runtime metrics for operator diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


class RuntimeMetrics:
    """Collect bounded process-local counters without affecting flight paths."""

    def __init__(self) -> None:
        self.started_at = _utc_now()
        self._started_monotonic = monotonic()
        self._lock = Lock()
        self._telemetry_received_total = 0
        self._telemetry_published_total = 0
        self._telemetry_withheld_total = 0
        self._telemetry_failed_total = 0
        self._telemetry_last_received_at: datetime | None = None
        self._telemetry_last_published_at: datetime | None = None
        self._backend_requests_total = 0
        self._backend_errors_total = 0
        self._backend_latency_total_ms = 0.0
        self._backend_last_latency_ms: float | None = None
        self._backend_last_success_at: datetime | None = None
        self._backend_last_error_at: datetime | None = None

    def record_telemetry_received(self, observed_at: datetime | None = None) -> None:
        with self._lock:
            self._telemetry_received_total += 1
            self._telemetry_last_received_at = observed_at or _utc_now()

    def record_telemetry_published(self, observed_at: datetime | None = None) -> None:
        with self._lock:
            self._telemetry_published_total += 1
            self._telemetry_last_published_at = observed_at or _utc_now()

    def record_telemetry_withheld(self) -> None:
        with self._lock:
            self._telemetry_withheld_total += 1

    def record_telemetry_failed(self) -> None:
        with self._lock:
            self._telemetry_failed_total += 1

    def record_backend_request(self, duration_s: float, *, success: bool) -> None:
        duration_ms = max(0.0, float(duration_s) * 1000)
        now = _utc_now()
        with self._lock:
            self._backend_requests_total += 1
            self._backend_latency_total_ms += duration_ms
            self._backend_last_latency_ms = duration_ms
            if success:
                self._backend_last_success_at = now
            else:
                self._backend_errors_total += 1
                self._backend_last_error_at = now

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-ready metrics; counters are monotonic for this process."""

        with self._lock:
            backend_requests = self._backend_requests_total
            return {
                "uptime_s": round(max(0.0, monotonic() - self._started_monotonic), 3),
                "started_at": _isoformat(self.started_at),
                "telemetry": {
                    "received_total": self._telemetry_received_total,
                    "published_total": self._telemetry_published_total,
                    "withheld_total": self._telemetry_withheld_total,
                    "failed_total": self._telemetry_failed_total,
                    "last_received_at": _isoformat(self._telemetry_last_received_at),
                    "last_published_at": _isoformat(self._telemetry_last_published_at),
                    # Publication is synchronous today, so there is no hidden
                    # queue. Keep this explicit for GCS diagnostics and future
                    # asynchronous backends.
                    "queue_depth": 0,
                },
                "backend": {
                    "requests_total": backend_requests,
                    "errors_total": self._backend_errors_total,
                    "average_latency_ms": round(
                        self._backend_latency_total_ms / backend_requests, 3
                    )
                    if backend_requests
                    else None,
                    "last_latency_ms": (
                        round(self._backend_last_latency_ms, 3)
                        if self._backend_last_latency_ms is not None
                        else None
                    ),
                    "last_success_at": _isoformat(self._backend_last_success_at),
                    "last_error_at": _isoformat(self._backend_last_error_at),
                },
            }
