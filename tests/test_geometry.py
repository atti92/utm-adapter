from datetime import datetime, timezone

import pytest

from utm_connector.domain import AltitudeDatum, Mission, Waypoint
from utm_connector.geometry import GeometryError, build_corridor


def mission(*, datum: AltitudeDatum = AltitudeDatum.AMSL) -> Mission:
    return Mission(
        vehicle_id="sitl-1",
        waypoints=[
            Waypoint(latitude=47.5000, longitude=19.0500, altitude={"meters": 100, "datum": datum}, sequence=0),
            Waypoint(latitude=47.5010, longitude=19.0520, altitude={"meters": 120, "datum": datum}, sequence=1),
        ],
        corridor_radius_m=30,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )


def test_corridor_is_projected_and_returns_valid_wgs84_polygon() -> None:
    result = build_corridor(mission())

    assert result.projected_crs == "EPSG:32634"
    assert result.volume.lower_altitude.meters == 100
    assert result.volume.upper_altitude.meters == 120
    assert len(result.volume.coordinates[0]) >= 4
    assert result.volume.coordinates[0][0] == result.volume.coordinates[0][-1]
    assert all(-180 <= longitude <= 180 and -90 <= latitude <= 90 for longitude, latitude in result.volume.coordinates[0])


def test_unknown_altitude_datum_is_rejected() -> None:
    with pytest.raises(GeometryError, match="altitude datum"):
        build_corridor(mission(datum=AltitudeDatum.UNKNOWN))


def test_nearly_collinear_backtracking_route_remains_a_valid_polygon() -> None:
    backtracking = Mission(
        vehicle_id="sitl-1",
        waypoints=[
            Waypoint(
                latitude=47.0,
                longitude=18.75,
                altitude={"meters": 100, "datum": AltitudeDatum.WGS84},
                sequence=0,
            ),
            Waypoint(
                latitude=47.0,
                longitude=19.0,
                altitude={"meters": 100, "datum": AltitudeDatum.WGS84},
                sequence=1,
            ),
            Waypoint(
                latitude=47.0,
                longitude=18.5,
                altitude={"meters": 100, "datum": AltitudeDatum.WGS84},
                sequence=2,
            ),
        ],
        corridor_radius_m=1,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    result = build_corridor(backtracking)

    assert result.volume.geometry_type == "Polygon"
    assert result.volume.coordinates[0][0] == result.volume.coordinates[0][-1]


def test_narrow_backtracking_route_keeps_single_polygon_after_inverse_projection() -> None:
    mission_with_retrace = Mission(
        vehicle_id="sitl-1",
        waypoints=[
            Waypoint(
                latitude=47.0,
                longitude=18.75,
                altitude={"meters": 100, "datum": AltitudeDatum.WGS84},
                sequence=0,
            ),
            Waypoint(
                latitude=47.0,
                longitude=19.5,
                altitude={"meters": 100, "datum": AltitudeDatum.WGS84},
                sequence=1,
            ),
            Waypoint(
                latitude=47.0,
                longitude=18.5,
                altitude={"meters": 100, "datum": AltitudeDatum.WGS84},
                sequence=2,
            ),
            Waypoint(
                latitude=47.0,
                longitude=19.0,
                altitude={"meters": 100, "datum": AltitudeDatum.WGS84},
                sequence=3,
            ),
        ],
        corridor_radius_m=1,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    result = build_corridor(mission_with_retrace)

    assert result.volume.geometry_type == "Polygon"
    assert result.volume.coordinates[0][0] == result.volume.coordinates[0][-1]
