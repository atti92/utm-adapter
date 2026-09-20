from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from scripts import openutm_demo


def test_compose_command_uses_the_selected_flight_blender_checkout(tmp_path: Path) -> None:
    config = openutm_demo.DemoConfig(flight_blender_root=tmp_path)

    assert openutm_demo._compose_base_command(config) == [
        "docker",
        "compose",
        "-f",
        str(tmp_path / "docker-compose-dev.yml"),
    ]


def test_demo_config_keeps_provider_and_connector_separate() -> None:
    config = openutm_demo.DemoConfig()

    assert config.provider_url == "http://127.0.0.1:8000"
    assert config.connector_url == "http://127.0.0.1:8001"
    assert config.gcs_udp_port == 14550
    assert config.connector_udp_port == 14551
    assert config.connector_record_path == config.run_dir / "connector-events.jsonl"


def test_px4_demo_uses_px4_external_api_port_by_default() -> None:
    parser = openutm_demo._build_parser()
    args = parser.parse_args(["--simulator", "px4"])

    config = openutm_demo._config_from_args(args)

    assert config.simulator == "px4"
    assert config.connector_udp_port == 14540
    assert config.px4_image == openutm_demo.DEFAULT_PX4_IMAGE


def test_px4_container_name_is_safe_for_docker_and_vehicle_specific() -> None:
    config = openutm_demo.DemoConfig(simulator="px4", vehicle_id="demo/vehicle 1")

    assert config.px4_container_name == "utm-adapter-px4-demo-vehicle-1"


def test_px4_prerequisites_do_not_require_an_ardupilot_checkout(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        simulator="px4",
        flight_blender_root=tmp_path / "missing-flight-blender",
        ardupilot_root=tmp_path / "missing-ardupilot",
    )
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert any("Flight Blender checkout not found" in failure for failure in failures)
    assert not any("ArduPilot checkout not found" in failure for failure in failures)


def test_px4_prerequisites_reject_custom_connector_port(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        simulator="px4",
        connector_udp_port=14541,
        flight_blender_root=tmp_path / "missing-flight-blender",
    )
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert any("stock SITL image requires connector UDP port 14540" in failure for failure in failures)


def test_px4_prerequisites_reject_custom_gcs_port(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        simulator="px4",
        gcs_udp_port=14560,
        flight_blender_root=tmp_path / "missing-flight-blender",
    )
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert any("stock SITL image requires GCS UDP port 14550" in failure for failure in failures)


def test_check_prerequisites_rejects_invalid_or_duplicate_simulator_ports(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        flight_blender_root=tmp_path / "missing-flight-blender",
        ardupilot_root=tmp_path / "missing-ardupilot",
        gcs_udp_port=14551,
        connector_udp_port=14551,
    )
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert "GCS UDP port and connector UDP port must be different" in failures


def test_compose_up_reuses_a_cached_provider_image(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(flight_blender_root=tmp_path)
    monkeypatch.setattr(openutm_demo, "_provider_image_is_available", lambda: True)

    command = openutm_demo._compose_up_command(config, compose_running=False)

    assert command[-2:] == ["up", "-d"]
    assert "--build" not in command


def test_compose_up_builds_when_the_provider_image_is_missing(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(flight_blender_root=tmp_path)
    monkeypatch.setattr(openutm_demo, "_provider_image_is_available", lambda: False)

    command = openutm_demo._compose_up_command(config, compose_running=False)

    assert command[-1] == "--build"


def test_provider_endpoint_is_ready_only_when_the_provider_port_serves_http(
    monkeypatch,
) -> None:
    config = openutm_demo.DemoConfig()
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: True)
    monkeypatch.setattr(openutm_demo, "probe_http_endpoint", lambda _url: (True, "200 OK"))

    assert openutm_demo._provider_endpoint_is_ready(config)


def test_provider_endpoint_is_not_ready_when_the_port_is_closed(monkeypatch) -> None:
    config = openutm_demo.DemoConfig()
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    assert not openutm_demo._provider_endpoint_is_ready(config)


def test_check_prerequisites_reports_missing_external_checkouts(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        flight_blender_root=tmp_path / "missing-flight-blender",
        ardupilot_root=tmp_path / "missing-ardupilot",
    )
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert any("Flight Blender checkout not found" in failure for failure in failures)
    assert any("ArduPilot checkout not found" in failure for failure in failures)


def test_check_prerequisites_reports_missing_requested_gcs(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        flight_blender_root=tmp_path / "missing-flight-blender",
        ardupilot_root=tmp_path / "missing-ardupilot",
        gcs="qgroundcontrol",
    )
    monkeypatch.setattr(openutm_demo, "_find_qgroundcontrol_command", lambda: None)
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert any("QGroundControl was requested" in failure for failure in failures)


def test_qgroundcontrol_detection_is_optional_for_auto_mode(monkeypatch) -> None:
    monkeypatch.setattr(openutm_demo, "_find_qgroundcontrol_command", lambda: None)

    assert openutm_demo._launch_gcs("auto") == (None, None)


def test_qgroundcontrol_detection_accepts_linux_command_name(monkeypatch) -> None:
    monkeypatch.setattr(openutm_demo.sys, "platform", "linux")
    monkeypatch.setattr(openutm_demo.os, "name", "posix")
    monkeypatch.setattr(
        openutm_demo.shutil,
        "which",
        lambda name: "/opt/QGroundControl" if name == "QGroundControl" else None,
    )

    assert openutm_demo._find_qgroundcontrol_command() == ["/opt/QGroundControl"]


def test_mission_planner_detection_finds_standard_windows_install(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "Mission Planner" / "MissionPlanner.exe"
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert openutm_demo._find_windows_installed_command(("Mission Planner/MissionPlanner.exe",)) == [str(executable)]


def test_requested_missing_qgroundcontrol_is_an_actionable_error(monkeypatch) -> None:
    monkeypatch.setattr(openutm_demo, "_find_qgroundcontrol_command", lambda: None)

    try:
        openutm_demo._launch_gcs("qgroundcontrol")
    except openutm_demo.DemoSetupError as exc:
        assert "QGroundControl" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("expected an actionable missing-GCS error")


def test_run_command_can_isolate_cleanup_process_and_bound_wait(monkeypatch) -> None:
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(openutm_demo.subprocess, "run", fake_run)

    result = openutm_demo._run_command(
        ["docker", "compose", "down"],
        start_new_session=True,
        timeout_s=30,
    )

    assert result is not None
    assert observed["start_new_session"] is True
    assert observed["timeout"] == 30


def test_demo_stop_masks_interrupts_while_reaping_children(monkeypatch) -> None:
    observed = []

    class FakeManagedProcess:
        def stop(self) -> None:
            observed.append(signal.getsignal(signal.SIGINT))

    runner = openutm_demo.DemoRunner(openutm_demo.DemoConfig())
    runner.processes = [FakeManagedProcess()]
    runner.provider_started_by_us = False

    runner.stop()

    assert observed == [signal.SIG_IGN]
    assert signal.getsignal(signal.SIGINT) != signal.SIG_IGN
