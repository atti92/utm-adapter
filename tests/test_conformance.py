from datetime import datetime, timezone

import pytest

from utm_connector.conformance import assess_conformance
from utm_connector.domain import AltitudeDatum, Mission, TelemetryQuality, VehicleTelemetry, Waypoint


def _mission() -> Mission:
    return Mission(
        vehicle_id="sitl-1",
        waypoints=[
            Waypoint(latitude=47.5000, longitude=19.0500, altitude={"meters": 100, "datum": AltitudeDatum.WGS84}, sequence=0),
            Waypoint(latitude=47.5010, longitude=19.0520, altitude={"meters": 120, "datum": AltitudeDatum.WGS84}, sequence=1),
        ],
        corridor_radius_m=30,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )


def _telemetry(**updates: object) -> VehicleTelemetry:
    payload = {
        "vehicle_id": "sitl-1",
        "observed_at": datetime.now(timezone.utc),
        "latitude": 47.5005,
        "longitude": 19.051,
        "altitude": {"meters": 110, "datum": AltitudeDatum.WGS84},
        "quality": TelemetryQuality.GOOD,
    }
    payload.update(updates)
    return VehicleTelemetry(**payload)


def test_conformance_classifies_inside_and_outside_positions() -> None:
    assert assess_conformance(_mission(), _telemetry()).state.value == "CONFORMING"
    outside = _telemetry(latitude=47.51, longitude=19.06)
    result = assess_conformance(_mission(), outside)
    assert result.state.value == "NON_CONFORMING"
    assert result.horizontal_distance_m > 0


def test_conformance_reports_near_boundary_and_altitude_violations() -> None:
    near_boundary = _telemetry(latitude=47.4999, longitude=19.0500)
    assert assess_conformance(_mission(), near_boundary, boundary_margin_m=20).state.value == "NEAR_BOUNDARY"
    too_high = _telemetry(altitude={"meters": 200, "datum": AltitudeDatum.WGS84})
    assert assess_conformance(_mission(), too_high).state.value == "NON_CONFORMING"
    assert assess_conformance(_mission(), too_high).vertical_distance_m == 80


def test_bad_telemetry_quality_is_unreliable() -> None:
    result = assess_conformance(_mission(), _telemetry(quality=TelemetryQuality.STALE))
    assert result.state.value == "TELEMETRY_UNRELIABLE"


def test_conformance_rejects_datum_mismatch() -> None:
    result = assess_conformance(
        _mission(),
        _telemetry(altitude={"meters": 110, "datum": AltitudeDatum.AGL}),
    )
    assert result.state.value == "TELEMETRY_UNRELIABLE"
