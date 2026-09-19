"""Explicit altitude-reference conversions used at provider boundaries.

MAVLink ``GLOBAL_POSITION_INT`` reports orthometric (AMSL) altitude while
Flight Blender's RID/declaration contract uses WGS84 ellipsoidal height.  The
conversion is not a constant offset: it depends on latitude, longitude, and a
geoid model.  This module therefore requires an explicit geoid grid instead of
silently guessing one.
"""

from __future__ import annotations

from pathlib import Path

from pyproj import Transformer

from .domain import Altitude, AltitudeDatum, Mission, VehicleTelemetry, Waypoint


class AltitudeConversionError(ValueError):
    """Raised when a requested altitude-reference conversion is unresolved."""


class AltitudeConverter:
    """Convert AMSL and WGS84 heights with an explicitly selected geoid grid."""

    def __init__(self, geoid_grid_path: str | Path) -> None:
        path = Path(geoid_grid_path).expanduser()
        if not path.is_file():
            raise AltitudeConversionError(f"geoid grid does not exist: {path}")
        self.geoid_grid_path = str(path)
        grid = str(path).replace(" ", r"\ ")
        self._amsl_to_wgs84 = Transformer.from_pipeline(
            "+proj=pipeline "
            "+step +proj=unitconvert +xy_in=deg +xy_out=rad "
            f"+step +proj=vgridshift +grids={grid} +multiplier=1 "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        )
        self._wgs84_to_amsl = Transformer.from_pipeline(
            "+proj=pipeline "
            "+step +proj=unitconvert +xy_in=deg +xy_out=rad "
            f"+step +proj=vgridshift +grids={grid} +multiplier=-1 "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        )

    def convert_altitude(
        self,
        altitude: Altitude,
        *,
        latitude: float,
        longitude: float,
        target: AltitudeDatum,
    ) -> Altitude:
        if altitude.datum == target:
            return altitude
        if altitude.datum not in {AltitudeDatum.AMSL, AltitudeDatum.WGS84}:
            raise AltitudeConversionError(
                f"cannot convert {altitude.datum.value} altitude to {target.value}; "
                "AGL requires a terrain/home reference"
            )
        if target not in {AltitudeDatum.AMSL, AltitudeDatum.WGS84}:
            raise AltitudeConversionError(f"unsupported target altitude datum: {target.value}")
        transformer = (
            self._amsl_to_wgs84
            if altitude.datum == AltitudeDatum.AMSL
            else self._wgs84_to_amsl
        )
        try:
            _longitude, _latitude, meters = transformer.transform(
                longitude,
                latitude,
                altitude.meters,
            )
        except Exception as exc:  # pyproj exposes several backend-specific exception types
            raise AltitudeConversionError(
                f"could not convert {altitude.datum.value} altitude using {self.geoid_grid_path}: {exc}"
            ) from exc
        return Altitude(meters=float(meters), datum=target)

    def convert_mission(self, mission: Mission, *, target: AltitudeDatum) -> Mission:
        waypoints = [
            Waypoint(
                latitude=waypoint.latitude,
                longitude=waypoint.longitude,
                altitude=self.convert_altitude(
                    waypoint.altitude,
                    latitude=waypoint.latitude,
                    longitude=waypoint.longitude,
                    target=target,
                ),
                sequence=waypoint.sequence,
            )
            for waypoint in mission.waypoints
        ]
        return mission.model_copy(update={"waypoints": waypoints})

    def convert_telemetry(
        self,
        telemetry: VehicleTelemetry,
        *,
        target: AltitudeDatum,
    ) -> VehicleTelemetry:
        return telemetry.model_copy(
            update={
                "altitude": self.convert_altitude(
                    telemetry.altitude,
                    latitude=telemetry.latitude,
                    longitude=telemetry.longitude,
                    target=target,
                )
            }
        )
