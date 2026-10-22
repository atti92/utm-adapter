import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.generate_test_mission import (
    build_mission,
    build_mission_planner_waypoints,
    build_qgroundcontrol_plan,
    write_demo_mission_files,
)
from utm_connector.missions import parse_mission_planner_waypoints, parse_qgroundcontrol_plan


def test_generated_mission_has_a_vertical_band(tmp_path: Path) -> None:
    output = tmp_path / "mission.json"
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "generate_test_mission.py"),
            "--output",
            str(output),
            "--altitude-m",
            "181",
            "--altitude-span-m",
            "4",
        ],
        check=True,
    )
    mission = json.loads(output.read_text(encoding="utf-8"))

    altitudes = [waypoint["altitude"]["meters"] for waypoint in mission["waypoints"]]
    assert altitudes == [179, 183]
    assert all(waypoint["altitude"]["datum"] == "WGS84" for waypoint in mission["waypoints"])


def test_demo_mission_artifacts_round_trip_through_production_parsers(tmp_path: Path) -> None:
    payload = build_mission(
        vehicle_id="sitl-1",
        latitude=47.4979,
        longitude=19.0402,
        altitude_m=120,
        altitude_span_m=4,
        duration_minutes=20,
        start_offset_minutes=1,
    )
    valid_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_until = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)

    qgc_mission = parse_qgroundcontrol_plan(
        build_qgroundcontrol_plan(payload),
        vehicle_id="sitl-1",
        valid_from=valid_from,
        valid_until=valid_until,
    )
    mp_mission = parse_mission_planner_waypoints(
        build_mission_planner_waypoints(payload),
        vehicle_id="sitl-1",
        valid_from=valid_from,
        valid_until=valid_until,
    )

    assert len(qgc_mission.waypoints) == 2
    assert len(mp_mission.waypoints) == 3
    assert qgc_mission.waypoints[1].longitude == mp_mission.waypoints[2].longitude

    paths = write_demo_mission_files(
        tmp_path,
        vehicle_id="demo-vehicle",
        latitude=51.5074,
        longitude=-0.1278,
        altitude_m=11,
    )
    assert set(paths) == {"canonical", "qgroundcontrol", "mission-planner"}
    assert paths["canonical"].is_file()
    assert paths["qgroundcontrol"].read_text(encoding="utf-8").startswith('{\n  "fileType": "Plan"')
    generated_qgc = json.loads(paths["qgroundcontrol"].read_text(encoding="utf-8"))
    generated_item = generated_qgc["mission"]["items"][0]
    assert generated_item["coordinate"] == [51.5074, -0.1278, 9]
    assert generated_item["params"] == [0, 0, 0, None]
    assert paths["mission-planner"].read_text(encoding="utf-8").startswith("QGC WPL 110\n")
    assert "51.5074" in paths["mission-planner"].read_text(encoding="utf-8")


def test_supervised_demo_uses_simulator_amsl_datum(tmp_path: Path) -> None:
    paths = write_demo_mission_files(tmp_path, altitude_m=137)
    mission = json.loads(paths["canonical"].read_text())
    assert {point["altitude"]["datum"] for point in mission["waypoints"]} == {"AMSL"}
    rows = paths["mission-planner"].read_text().splitlines()
    assert rows[1].startswith("0 1 0 16 ")
    assert rows[2].startswith("1 0 5 22 ")
    assert rows[3].startswith("2 0 5 21 ")
