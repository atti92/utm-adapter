"""Deterministic local conformance assessment for active operations."""

from __future__ import annotations

from datetime import datetime, timezone

from pyproj import CRS, Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from .domain import (
    AltitudeDatum,
    ConformanceState,
    Mission,
    StrictModel,
    TelemetryQuality,
    VehicleTelemetry,
)
from .geometry import build_corridor


class ConformanceAssessment(StrictModel):
    state: ConformanceState
    horizontal_distance_m: float
    vertical_distance_m: float = 0
    reason: str
    assessed_at: datetime


def assess_conformance(
    mission: Mission,
    telemetry: VehicleTelemetry,
    *,
    boundary_margin_m: float = 10,
) -> ConformanceAssessment:
    """Classify telemetry against a mission's horizontal and vertical volume.

    Horizontal distance is measured in the mission's projected metre-based CRS.
    For a point inside the corridor it is the distance to the corridor boundary;
    for a point outside it is the distance back to the corridor. Vertical
    distance is the distance to the nearest altitude limit when outside.
    """

    if telemetry.vehicle_id != mission.vehicle_id:
        raise ValueError("telemetry vehicle_id does not match mission")
    if boundary_margin_m <= 0:
        raise ValueError("boundary_margin_m must be positive")

    now = datetime.now(timezone.utc)
    if telemetry.quality in {
        TelemetryQuality.UNKNOWN,
        TelemetryQuality.STALE,
        TelemetryQuality.INVALID,
        TelemetryQuality.LOST,
    }:
        return ConformanceAssessment(
            state=ConformanceState.TELEMETRY_UNRELIABLE,
            horizontal_distance_m=0,
            reason=f"telemetry quality is {telemetry.quality.value}",
            assessed_at=now,
        )

    corridor = build_corridor(mission)
    if telemetry.altitude.datum != corridor.volume.lower_altitude.datum:
        return ConformanceAssessment(
            state=ConformanceState.TELEMETRY_UNRELIABLE,
            horizontal_distance_m=0,
            reason="telemetry and mission altitude datums do not match",
            assessed_at=now,
        )

    polygon = shape(
        {
            "type": corridor.volume.geometry_type,
            "coordinates": corridor.volume.coordinates,
        }
    )
    projected_crs = CRS.from_user_input(corridor.projected_crs)
    forward = Transformer.from_crs(CRS.from_epsg(4326), projected_crs, always_xy=True)
    projected_polygon = transform(forward.transform, polygon)
    point = transform(
        forward.transform,
        Point(telemetry.longitude, telemetry.latitude),
    )
    inside = projected_polygon.covers(point)
    horizontal_distance = (
        projected_polygon.boundary.distance(point)
        if inside
        else projected_polygon.distance(point)
    )

    lower = corridor.volume.lower_altitude.meters
    upper = corridor.volume.upper_altitude.meters
    altitude = telemetry.altitude.meters
    vertical_distance = 0.0
    if altitude < lower:
        vertical_distance = lower - altitude
    elif altitude > upper:
        vertical_distance = altitude - upper

    if vertical_distance > 0:
        state = ConformanceState.NON_CONFORMING
        reason = "altitude is outside the operational volume"
    elif horizontal_distance <= boundary_margin_m:
        state = ConformanceState.NEAR_BOUNDARY
        reason = "position is within the conformance boundary margin"
    elif inside:
        state = ConformanceState.CONFORMING
        reason = "position and altitude are inside the operational volume"
    else:
        state = ConformanceState.NON_CONFORMING
        reason = "position is outside the operational volume"

    return ConformanceAssessment(
        state=state,
        horizontal_distance_m=round(horizontal_distance, 3),
        vertical_distance_m=round(vertical_distance, 3),
        reason=reason,
        assessed_at=now,
    )
