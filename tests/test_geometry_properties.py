from datetime import datetime, timezone
from uuid import uuid4

from hypothesis import given, settings, strategies as st
from shapely.geometry import Point, shape

from utm_connector.domain import AltitudeDatum, Mission, Waypoint
from utm_connector.geometry import build_corridor


route_points = st.lists(
    st.tuples(
        st.floats(min_value=47.0, max_value=48.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=18.5, max_value=19.5, allow_nan=False, allow_infinity=False),
    ),
    min_size=2,
    max_size=6,
    unique=True,
)


def make_mission(
    points: list[tuple[float, float]],
    *,
    corridor_radius_m: float,
    mission_id=None,
    source: str = "property-test",
) -> Mission:
    return Mission(
        mission_id=mission_id or uuid4(),
        vehicle_id="property-test-vehicle",
        waypoints=[
            Waypoint(
                latitude=latitude,
                longitude=longitude,
                altitude={"meters": 100 + index, "datum": AltitudeDatum.WGS84},
                sequence=index,
            )
            for index, (latitude, longitude) in enumerate(points)
        ],
        corridor_radius_m=corridor_radius_m,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        source=source,
    )


@settings(max_examples=25, deadline=None)
@given(
    points=route_points,
    corridor_radius_m=st.floats(
        min_value=1.0,
        max_value=500.0,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    ),
)
def test_generated_corridor_is_valid_and_covers_every_waypoint(
    points: list[tuple[float, float]], corridor_radius_m: float
) -> None:
    mission = make_mission(points, corridor_radius_m=corridor_radius_m)

    result = build_corridor(mission)
    polygon = shape({"type": result.volume.geometry_type, "coordinates": result.volume.coordinates})
    ring = result.volume.coordinates[0]

    assert result.projected_crs == "EPSG:32634"
    assert polygon.is_valid
    assert not polygon.is_empty
    assert ring[0] == ring[-1]
    assert all(polygon.covers(Point(longitude, latitude)) for latitude, longitude in points)


@settings(max_examples=20, deadline=None)
@given(points=route_points, corridor_radius_m=st.floats(min_value=1.0, max_value=500.0))
def test_corridor_output_is_deterministic_for_equivalent_mission_sources(
    points: list[tuple[float, float]], corridor_radius_m: float
) -> None:
    first = build_corridor(
        make_mission(
            points,
            corridor_radius_m=corridor_radius_m,
            mission_id=uuid4(),
            source="qgroundcontrol",
        )
    )
    second = build_corridor(
        make_mission(
            points,
            corridor_radius_m=corridor_radius_m,
            mission_id=uuid4(),
            source="mission-planner",
        )
    )

    assert first == second
