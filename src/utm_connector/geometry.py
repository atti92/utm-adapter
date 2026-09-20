"""Deterministic geospatial operations for canonical missions."""

from __future__ import annotations

from math import floor
from typing import Iterable

from pyproj import CRS, Transformer
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import transform

from .domain import Altitude, AltitudeDatum, CorridorGeometry, Mission, OperationalVolume


class GeometryError(ValueError):
    """Raised when a mission cannot produce a safe operational volume."""


def build_corridor(mission: Mission) -> CorridorGeometry:
    """Buffer a WGS84 route in a projected CRS and return GeoJSON coordinates.

    Coordinates in the returned volume are GeoJSON order: [longitude, latitude].
    The route is never buffered in angular WGS84 units.
    """

    _validate_altitudes(mission)
    longitudes = [waypoint.longitude for waypoint in mission.waypoints]
    latitudes = [waypoint.latitude for waypoint in mission.waypoints]
    if max(longitudes) - min(longitudes) > 6:
        raise GeometryError("route spans more than one UTM zone; split or reproject it explicitly")

    projected_crs = _select_projected_crs(longitudes, latitudes)
    forward = Transformer.from_crs(CRS.from_epsg(4326), projected_crs, always_xy=True)
    reverse = Transformer.from_crs(projected_crs, CRS.from_epsg(4326), always_xy=True)
    route = LineString((waypoint.longitude, waypoint.latitude) for waypoint in mission.waypoints)
    projected_route = transform(forward.transform, route)
    buffered = projected_route.buffer(
        mission.corridor_radius_m,
        cap_style="round",
        join_style="round",
        quad_segs=8,
    )
    restored = transform(reverse.transform, buffered)
    if not restored.is_valid:
        # Inverse projection can introduce tiny self-intersections at nearly
        # collinear/backtracking route vertices. A centimetre-scale WGS84
        # cleanup removes those numerical artefacts without materially
        # increasing the operational footprint of normal metre-scale corridors.
        restored = restored.buffer(1e-7)
    if not isinstance(restored, Polygon) or restored.is_empty or not restored.is_valid:
        raise GeometryError("generated corridor is not a valid polygon")

    coordinates = mapping(restored)["coordinates"]
    altitude = [waypoint.altitude.meters for waypoint in mission.waypoints]
    datum = mission.waypoints[0].altitude.datum
    volume = OperationalVolume(
        coordinates=coordinates,
        lower_altitude=Altitude(meters=min(altitude), datum=datum),
        upper_altitude=Altitude(meters=max(altitude), datum=datum),
    )
    return CorridorGeometry(
        mission_hash=mission.canonical_hash(),
        projected_crs=projected_crs.to_string(),
        corridor_radius_m=mission.corridor_radius_m,
        volume=volume,
    )


def _validate_altitudes(mission: Mission) -> None:
    datums = {waypoint.altitude.datum for waypoint in mission.waypoints}
    if AltitudeDatum.UNKNOWN in datums:
        raise GeometryError("altitude datum is required before generating an operational volume")
    if len(datums) != 1:
        raise GeometryError("all waypoints must use the same altitude datum")


def _select_projected_crs(longitudes: Iterable[float], latitudes: Iterable[float]) -> CRS:
    longitude_values = tuple(longitudes)
    latitude_values = tuple(latitudes)
    mean_longitude = sum(longitude_values) / len(longitude_values)
    mean_latitude = sum(latitude_values) / len(latitude_values)
    if -80 <= mean_latitude <= 84:
        zone = min(60, max(1, floor((mean_longitude + 180) / 6) + 1))
        epsg = (32600 if mean_latitude >= 0 else 32700) + zone
        return CRS.from_epsg(epsg)
    # UTM is not defined at the poles; use a local metre-based projection there.
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={mean_latitude} +lon_0={mean_longitude} "
        "+datum=WGS84 +units=m +no_defs"
    )
