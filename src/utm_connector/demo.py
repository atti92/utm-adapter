"""Deterministic local vehicle feed for an operator-console demo."""

from __future__ import annotations

from datetime import datetime, timezone
from math import floor
from threading import Event, Thread
from time import monotonic
from typing import Optional

from .domain import (
    TelemetryQuality,
    VehicleConnectionState,
    VehicleHealth,
    VehicleIdentity,
    VehicleStateSnapshot,
    VehicleTelemetry,
)


class DemoVehiclePublisher:
    """Publish a visible, non-commanding vehicle around the sample route."""

    _route = (
        (47.4979, 19.0402),
        (47.4992, 19.0420),
        (47.5000, 19.0390),
    )

    def __init__(self, service, vehicle_id: str, interval_s: float = 1.0) -> None:
        self.service = service
        self.vehicle_id = vehicle_id
        self.interval_s = interval_s
        self._stop = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.publish_once()
        self._stop.clear()
        self._thread = Thread(target=self._run, name=f"demo-{self.vehicle_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_s + 0.5))
            self._thread = None

    def publish_once(self, now: Optional[datetime] = None) -> VehicleStateSnapshot:
        observed_at = now or datetime.now(timezone.utc)
        latitude, longitude = self._position()
        telemetry = VehicleTelemetry(
            vehicle_id=self.vehicle_id,
            observed_at=observed_at,
            latitude=latitude,
            longitude=longitude,
            # Keep the built-in vehicle inside the sample route's 135–140 m
            # WGS84 volume so the one-command demo demonstrates a healthy
            # conformance state instead of manufacturing an altitude alert.
            altitude={"meters": 137, "datum": "WGS84"},
            heading_deg=90,
            groundspeed_mps=4.0,
            quality=TelemetryQuality.GOOD,
        )
        snapshot = VehicleStateSnapshot(
            identity=VehicleIdentity(
                connector_vehicle_id=self.vehicle_id,
                mavlink_system_id=1,
                mavlink_component_ids=[1],
                autopilot_type="DEMO",
                vehicle_type="MULTIROTOR",
                firmware_version="demo",
            ),
            connection_state=VehicleConnectionState.CONNECTED,
            telemetry=telemetry,
            quality=TelemetryQuality.GOOD,
            health=VehicleHealth(
                heartbeat_age_s=0,
                position_age_s=0,
                gps_fix_type=3,
                satellites_visible=12,
                battery_remaining_pct=87,
                battery_voltage_v=16.2,
                armed=False,
            ),
        )
        return self.service.ingest_vehicle_snapshot(snapshot)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.publish_once()
            except Exception as exc:  # pragma: no cover - defensive thread boundary
                self.service.record_event(
                    "DEMO_TELEMETRY_ERROR",
                    vehicle_id=self.vehicle_id,
                    severity="ERROR",
                    details={"error": str(exc)},
                )

    def _position(self) -> tuple[float, float]:
        # Complete one lap in 24 seconds and interpolate each route segment.
        segment = (monotonic() / 8.0) % len(self._route)
        index = floor(segment)
        fraction = segment - index
        start = self._route[index]
        end = self._route[(index + 1) % len(self._route)]
        return (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )
