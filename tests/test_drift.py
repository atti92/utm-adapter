from datetime import datetime, timedelta, timezone

from utm_connector.domain import Mission, MissionDriftClassification
from utm_connector.drift import compare_missions


def _mission(**overrides: object) -> Mission:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    data = {
        "mission_id": "00000000-0000-0000-0000-000000000001",
        "vehicle_id": "sitl-1",
        "valid_from": start,
        "valid_until": start + timedelta(minutes=30),
        "source": "qgroundcontrol",
        "waypoints": [
            {"sequence": 0, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 20, "datum": "AGL"}},
            {"sequence": 1, "latitude": 47.501, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
        ],
    }
    data.update(overrides)
    return Mission(**data)


def test_equivalent_missions_from_different_sources_have_no_drift() -> None:
    report = compare_missions(_mission(), _mission(source="mavlink"))

    assert report.classification == MissionDriftClassification.NON_OPERATIONAL_CHANGE
    assert report.changed_fields == ["source"]
    assert report.submitted_mission_hash == report.current_mission_hash


def test_route_drift_is_classified() -> None:
    waypoints = [
        {"sequence": 0, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 20, "datum": "AGL"}},
        {"sequence": 1, "latitude": 47.502, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
    ]

    report = compare_missions(_mission(), _mission(waypoints=waypoints))

    assert report.classification == MissionDriftClassification.ROUTE_CHANGED
    assert report.changed_fields == ["waypoints[1].latitude"]


def test_mixed_operational_drift_is_unknown() -> None:
    waypoints = [
        {"sequence": 0, "latitude": 47.5, "longitude": 19.0, "altitude": {"meters": 21, "datum": "AGL"}},
        {"sequence": 1, "latitude": 47.502, "longitude": 19.001, "altitude": {"meters": 25, "datum": "AGL"}},
    ]

    report = compare_missions(_mission(), _mission(waypoints=waypoints))

    assert report.classification == MissionDriftClassification.UNKNOWN_CHANGE
    assert report.changed_fields == ["waypoints[0].altitude.meters", "waypoints[1].latitude"]
