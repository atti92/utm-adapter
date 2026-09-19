import json
import subprocess
import sys
from pathlib import Path


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
