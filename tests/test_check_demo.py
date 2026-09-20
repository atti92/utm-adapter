from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts import check_demo


def test_demo_check_parser_defaults_to_operator_friendly_auto_gcs() -> None:
    args = check_demo._parser().parse_args([])

    assert args.simulator == "ardupilot"
    assert args.topology == "split"
    assert args.gcs == "auto"
    assert args.strict_router is False


def test_demo_config_selects_px4_external_api_port() -> None:
    args = check_demo._parser().parse_args(["--simulator", "px4"])

    config = check_demo._demo_config(args)

    assert config.connector_udp_port == check_demo.openutm_demo.DEFAULT_PX4_CONNECTOR_PORT


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
    monkeypatch.setattr(check_demo.openutm_demo, "_find_router_command", lambda: None)
    monkeypatch.setattr(check_demo.openutm_demo, "_find_qgroundcontrol_command", lambda: None)
    monkeypatch.setattr(check_demo.openutm_demo, "_find_mission_planner_command", lambda: None)
    monkeypatch.setattr(check_demo.Path, "is_dir", lambda _self: False)

    assert check_demo.main(["--simulator", "px4", "--gcs", "none"]) == 0
    assert "[ok] demo host is ready" in capsys.readouterr().out


def test_demo_check_strict_router_fails_when_optional_router_check_fails(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(check_demo, "_print_required", lambda _config: True)
    monkeypatch.setattr(check_demo.check_mavlink_router, "validate", lambda _path: [])
    monkeypatch.setattr(check_demo.openutm_demo, "_find_router_command", lambda: None)
    monkeypatch.setattr(check_demo.openutm_demo, "_router_image_is_available", lambda _config: False)
    monkeypatch.setattr(check_demo.openutm_demo, "_find_qgroundcontrol_command", lambda: None)
    monkeypatch.setattr(check_demo.openutm_demo, "_find_mission_planner_command", lambda: None)
    monkeypatch.setattr(check_demo.Path, "is_dir", lambda _self: False)

    assert check_demo.main(["--strict-router"]) == 1


def test_setup_guidance_distinguishes_px4_from_ardupilot(capsys) -> None:
    config = check_demo.openutm_demo.DemoConfig(simulator="px4")

    check_demo._print_setup_guidance(config)

    output = capsys.readouterr().out
    assert "no PX4 or ArduPilot checkout is required" in output
    assert "browser operator console" in output
