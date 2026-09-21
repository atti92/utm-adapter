from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from utm_connector.altitude import AltitudeConversionError, AltitudeConverter
from utm_connector.domain import Altitude, AltitudeDatum, AltitudeReference, Mission, VehicleTelemetry


def _mission(datum: AltitudeDatum = AltitudeDatum.AMSL) -> Mission:
    start = datetime.now(timezone.utc)
    return Mission(
        vehicle_id="sitl-1",
        valid_from=start,
        valid_until=start + timedelta(minutes=20),
        waypoints=[
            {
                "sequence": 0,
                "latitude": 47.4979,
                "longitude": 19.0402,
                "altitude": {"meters": 137, "datum": datum},
            },
            {
                "sequence": 1,
                "latitude": 47.4984,
                "longitude": 19.0407,
                "altitude": {"meters": 137, "datum": datum},
            },
        ],
    )


def _grid_path() -> Path:
    candidates = (
        Path("/opt/homebrew/Cellar/proj/9.7.0/share/proj/us_nga_egm96_15.tif"),
        Path("/usr/local/share/proj/us_nga_egm96_15.tif"),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


@pytest.mark.skipif(not _grid_path().is_file(), reason="host does not provide an EGM96 geoid grid")
def test_egm96_conversion_is_coordinate_aware() -> None:
    converter = AltitudeConverter(_grid_path())

    converted = converter.convert_altitude(
        Altitude(meters=137, datum=AltitudeDatum.AMSL),
        latitude=47.4979,
        longitude=19.0402,
        target=AltitudeDatum.WGS84,
    )

    assert converted.datum == AltitudeDatum.WGS84
    assert converted.meters > 150
    assert converted.meters != 137


def test_converter_rejects_missing_grid_and_unresolved_agl() -> None:
    with pytest.raises(AltitudeConversionError, match="does not exist"):
        AltitudeConverter("/does/not/exist/egm96.tif")


def test_converter_keeps_same_datum_and_converts_models() -> None:
    converter = object.__new__(AltitudeConverter)
    converter.geoid_grid_path = "test-grid"

    class FakeTransformer:
        def transform(self, _longitude, _latitude, meters):
            return _longitude, _latitude, meters + 10

    converter._amsl_to_wgs84 = FakeTransformer()
    converter._wgs84_to_amsl = FakeTransformer()

    same = converter.convert_altitude(
        Altitude(meters=137, datum=AltitudeDatum.AMSL),
        latitude=47.5,
        longitude=19.0,
        target=AltitudeDatum.AMSL,
    )
    assert same.meters == 137

    mission = converter.convert_mission(_mission(), target=AltitudeDatum.WGS84)
    assert {waypoint.altitude.datum for waypoint in mission.waypoints} == {AltitudeDatum.WGS84}
    assert mission.waypoints[0].altitude.meters == 147

    telemetry = VehicleTelemetry(
        vehicle_id="sitl-1",
        observed_at=datetime.now(timezone.utc),
        latitude=47.4979,
        longitude=19.0402,
        altitude={"meters": 137, "datum": AltitudeDatum.AMSL},
    )
    converted_telemetry = converter.convert_telemetry(telemetry, target=AltitudeDatum.WGS84)
    assert converted_telemetry.altitude.meters == 147

    with pytest.raises(AltitudeConversionError, match="AGL"):
        converter.convert_altitude(
            Altitude(meters=10, datum=AltitudeDatum.AGL),
            latitude=47.5,
            longitude=19.0,
            target=AltitudeDatum.WGS84,
        )


def test_converter_resolves_agl_from_an_explicit_home_reference() -> None:
    converter = object.__new__(AltitudeConverter)
    converter.geoid_grid_path = "test-grid"

    class FakeTransformer:
        def transform(self, _longitude, _latitude, meters):
            return _longitude, _latitude, meters + 10

    converter._amsl_to_wgs84 = FakeTransformer()
    converter._wgs84_to_amsl = FakeTransformer()
    reference = AltitudeReference(
        latitude=47.5,
        longitude=19.0,
        altitude={"meters": 137, "datum": AltitudeDatum.AMSL},
    )

    converted = converter.convert_altitude(
        Altitude(meters=20, datum=AltitudeDatum.AGL),
        latitude=47.501,
        longitude=19.001,
        target=AltitudeDatum.WGS84,
        reference=reference,
    )

    assert converted.datum == AltitudeDatum.WGS84
    assert converted.meters == 167
