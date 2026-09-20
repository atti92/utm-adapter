from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts import check_demo


def test_demo_check_parser_defaults_to_operator_friendly_auto_gcs() -> None:
    args = check_demo._parser().parse_args([])

    assert args.simulator == "ardupilot"
    assert args.gcs == "auto"
    assert args.strict_router is False


def test_demo_check_does_not_fail_when_optional_native_apps_are_missing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    config = check_demo.openutm_demo.DemoConfig(
        simulator="px4",
        gcs="none",
        flight_blender_root=tmp_path / "flight-blender",
    )
    monkeypatch.setattr(check_demo, "_print_required", lambda _config: True)
    monkeypatch.setattr(check_demo.check_mavlink_router, "validate", lambda _path: [])
    monkeypatch.setattr(check_demo.shutil, "which", lambda _name: None)
    monkeypatch.setattr(check_demo.openutm_demo, "_find_qgroundcontrol_command", lambda: None)
    monkeypatch.setattr(check_demo.openutm_demo, "_find_mission_planner_command", lambda: None)
    monkeypatch.setattr(check_demo.Path, "is_dir", lambda _self: False)

    assert check_demo.main(["--simulator", "px4", "--gcs", "none"]) == 0
    assert "[ok] demo host is ready" in capsys.readouterr().out
