from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from utm_connector.domain import Altitude, AltitudeDatum, Mission, Waypoint


def mission(**overrides: object) -> Mission:
    now = datetime.now(timezone.utc)
    data = {
        "vehicle_id": "sitl-1",
        "valid_from": now,
        "valid_until": now + timedelta(minutes=30),
        "source": "test",
        "waypoints": [
            {"sequence": 0, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 20, "datum": "AGL"}},
            {"sequence": 1, "latitude": 47.501, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
        ],
    }
    data.update(overrides)
    return Mission(**data)


def test_mission_hash_is_stable_and_excludes_transport_id() -> None:
    fixed_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = mission(valid_from=fixed_start, valid_until=fixed_start + timedelta(minutes=30))
    second = mission(valid_from=fixed_start, valid_until=fixed_start + timedelta(minutes=30))
    assert first.canonical_hash() == second.canonical_hash()


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        mission(valid_from=datetime(2026, 1, 1))


def test_unknown_altitude_datum_is_explicit() -> None:
    altitude = Altitude(meters=10, datum=AltitudeDatum.UNKNOWN)
    assert altitude.datum == AltitudeDatum.UNKNOWN


def test_waypoint_sequence_must_be_contiguous() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        mission(waypoints=[
            {"sequence": 1, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 20, "datum": "AGL"}},
            {"sequence": 2, "latitude": 47.501, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
        ])


def test_coordinates_are_bounded() -> None:
    with pytest.raises(ValidationError):
        Waypoint(sequence=0, latitude=91, longitude=19, altitude={"meters": 1, "datum": "AGL"})


def test_non_finite_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Waypoint(sequence=0, latitude=float("nan"), longitude=19, altitude={"meters": 1, "datum": "AGL"})
