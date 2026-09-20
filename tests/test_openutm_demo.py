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


def test_verify_flag_is_carried_into_demo_config() -> None:
    parser = openutm_demo._build_parser()
    args = parser.parse_args(["--verify", "--no-browser"])

    config = openutm_demo._config_from_args(args)

    assert config.verify is True
    assert config.open_browser is False


def test_router_topology_is_carried_into_demo_config() -> None:
    parser = openutm_demo._build_parser()
    args = parser.parse_args(["--topology", "router", "--no-browser"])

    config = openutm_demo._config_from_args(args)

    assert config.topology == "router"
    assert config.router_port == openutm_demo.DEFAULT_ROUTER_INPUT_PORT
    assert config.router_config == openutm_demo.DEFAULT_ROUTER_CONFIG
    assert config.router_runtime == openutm_demo.DEFAULT_ROUTER_RUNTIME


def test_check_run_hint_preserves_the_selected_px4_demo_path() -> None:
    config = openutm_demo.DemoConfig(
        simulator="px4",
        connector_udp_port=openutm_demo.DEFAULT_PX4_CONNECTOR_PORT,
        home="51.5074,-0.1278,11,90",
        gcs="none",
        open_browser=False,
    )

    assert openutm_demo._check_run_hint(config) == (
        "uv run python scripts/openutm_demo.py --simulator px4 "
        "--home 51.5074,-0.1278,11,90 --gcs none --no-browser"
    )


def test_px4_container_name_is_safe_for_docker_and_vehicle_specific() -> None:
    config = openutm_demo.DemoConfig(simulator="px4", vehicle_id="demo/vehicle 1")

    assert config.px4_container_name == "utm-adapter-px4-demo-vehicle-1"


def test_px4_demo_passes_shared_home_to_sitl_launcher(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        simulator="px4",
        adapter_root=tmp_path,
        home="51.5074,-0.1278,11,90",
    )
    observed: dict[str, object] = {}

    def fake_start(name, command, **kwargs):
        observed["name"] = name
        observed["command"] = list(command)
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(openutm_demo, "_start_new_process", fake_start)
    runner = openutm_demo.DemoRunner(config)

    openutm_demo._start_sitl(runner)

    command = observed["command"]
    assert isinstance(command, list)
    assert "--home" in command
    home_index = command.index("--home")
    assert command[home_index + 1] == "51.5074,-0.1278,11,90"


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


def test_px4_prerequisites_report_occupied_udp_port(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        simulator="px4",
        flight_blender_root=tmp_path / "missing-flight-blender",
    )
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)
    monkeypatch.setattr(
        openutm_demo,
        "udp_port_is_available",
        lambda _host, port: port != openutm_demo.DEFAULT_PX4_GCS_PORT,
    )

    failures = openutm_demo.check_prerequisites(config)

    assert "GCS UDP port 127.0.0.1:14550 is already in use" in failures


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


def test_router_prerequisites_require_native_router_and_ardupilot(
    tmp_path: Path, monkeypatch
) -> None:
    config = openutm_demo.DemoConfig(
        topology="router",
        simulator="px4",
        router_runtime="native",
        flight_blender_root=tmp_path / "missing-flight-blender",
    )
    monkeypatch.setattr(openutm_demo, "_find_router_command", lambda: None)
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert any("requires the ArduPilot SITL launcher" in failure for failure in failures)
    assert any("mavlink-routerd was not found" in failure for failure in failures)


def test_router_runtime_auto_uses_docker_when_native_binary_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    source_root = tmp_path / "mavlink-router"
    (source_root / "examples").mkdir(parents=True)
    (source_root / "examples" / "Dockerfile.ubuntu").touch()
    config = openutm_demo.DemoConfig(
        topology="router",
        router_source_root=source_root,
        router_image="router:test",
    )
    monkeypatch.setattr(openutm_demo, "_find_router_command", lambda: None)
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_router_image_is_available", lambda _config: False)

    assert openutm_demo._select_router_runtime(config) == "docker"


def test_docker_router_host_ip_accepts_explicit_ipv4_override(monkeypatch) -> None:
    monkeypatch.setenv("MAVLINK_ROUTER_DOCKER_HOST", "192.168.65.254")

    assert openutm_demo._docker_router_host_ip(openutm_demo.DemoConfig()) == "192.168.65.254"


def test_router_sitl_command_uses_single_output(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        topology="router",
        adapter_root=tmp_path,
        ardupilot_root=tmp_path / "ardupilot",
    )
    observed: dict[str, object] = {}

    def fake_start(name, command, **kwargs):
        observed["name"] = name
        observed["command"] = list(command)
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(openutm_demo, "_start_new_process", fake_start)
    runner = openutm_demo.DemoRunner(config)

    openutm_demo._start_sitl(runner)

    command = observed["command"]
    assert isinstance(command, list)
    assert "--router-port" in command
    assert "--gcs-port" not in command
    assert "--connector-port" not in command


def test_router_process_uses_checked_in_config(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(topology="router", adapter_root=tmp_path)
    observed: dict[str, object] = {}

    def fake_start(name, command, **kwargs):
        observed["name"] = name
        observed["command"] = list(command)
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(openutm_demo, "_find_router_command", lambda: "/usr/local/bin/mavlink-routerd")
    monkeypatch.setattr(openutm_demo, "_start_new_process", fake_start)

    openutm_demo._start_router(openutm_demo.DemoRunner(config))

    assert observed["name"] == "MAVLink Router"
    assert observed["command"] == [
        "/usr/local/bin/mavlink-routerd",
        "--conf-file",
        str(openutm_demo.DEFAULT_ROUTER_CONFIG),
    ]


def test_router_process_uses_docker_fallback_command(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        topology="router",
        router_runtime="docker",
        adapter_root=tmp_path,
        router_image="router:test",
    )
    observed: dict[str, object] = {}

    def fake_start(name, command, **kwargs):
        observed["name"] = name
        observed["command"] = list(command)
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(openutm_demo, "_select_router_runtime", lambda _config: "docker")
    monkeypatch.setattr(openutm_demo, "_ensure_router_image", lambda _config: None)
    monkeypatch.setattr(openutm_demo, "_docker_router_host_ip", lambda _config: "192.168.65.254")
    monkeypatch.setattr(openutm_demo, "_start_new_process", fake_start)

    runner = openutm_demo.DemoRunner(config)
    openutm_demo._start_router(runner)

    command = observed["command"]
    assert isinstance(command, list)
    assert command[:6] == [
        "docker",
        "run",
        "--rm",
        "--name",
        config.router_container_name,
        "--add-host",
    ]
    assert "host.docker.internal:host-gateway" in command
    assert "router:test" in command
    assert "192.168.65.254:14550" in command
    assert "192.168.65.254:14551" in command


def test_wait_for_vehicle_reports_child_process_exit(tmp_path: Path) -> None:
    class ExitedProcess:
        name = "MAVLink Router"
        process = type("Process", (), {"poll": lambda _self: 7})()

    runner = openutm_demo.DemoRunner(
        openutm_demo.DemoConfig(adapter_root=tmp_path),
        processes=[ExitedProcess()],
    )

    try:
        runner._wait_for_vehicle()
    except openutm_demo.DemoSetupError as exc:
        assert "MAVLink Router exited with code 7" in str(exc)
        assert str(tmp_path / ".local" / "openutm-demo") in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("expected the child-process failure to be reported")


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


def test_check_prerequisites_rejects_duplicate_http_ports(tmp_path: Path, monkeypatch) -> None:
    config = openutm_demo.DemoConfig(
        flight_blender_root=tmp_path / "missing-flight-blender",
        provider_port=8100,
        connector_port=8100,
    )
    monkeypatch.setattr(openutm_demo, "_command_available", lambda _command: (True, "ok"))
    monkeypatch.setattr(openutm_demo, "_find_geoid_grid", lambda: tmp_path / "grid.tif")
    monkeypatch.setattr(openutm_demo, "port_is_reachable", lambda _host, _port: False)

    failures = openutm_demo.check_prerequisites(config)

    assert "Flight Blender HTTP port and connector HTTP port must be different" in failures


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


def test_demo_check_uses_the_selected_simulator_and_gcs(tmp_path: Path) -> None:
    parser = openutm_demo._build_parser()
    args = parser.parse_args(["--simulator", "px4", "--gcs", "none"])

    config = openutm_demo.DemoConfig(
        simulator=args.simulator,
        gcs=args.gcs,
        flight_blender_root=tmp_path / "flight-blender",
    )

    assert config.simulator == "px4"
    assert config.gcs == "none"


def test_qgroundcontrol_detection_is_optional_for_auto_mode(monkeypatch) -> None:
    monkeypatch.setattr(openutm_demo, "_find_qgroundcontrol_command", lambda: None)
    monkeypatch.setattr(openutm_demo, "_find_mission_planner_command", lambda: None)

    assert openutm_demo._launch_gcs("auto") == (None, None)


def test_auto_gcs_falls_back_to_mission_planner(monkeypatch) -> None:
    monkeypatch.setattr(openutm_demo, "_find_qgroundcontrol_command", lambda: None)
    monkeypatch.setattr(openutm_demo, "_find_mission_planner_command", lambda: ["MissionPlanner.exe"])
    monkeypatch.setattr(openutm_demo.subprocess, "Popen", lambda *_args, **_kwargs: object())

    assert openutm_demo._launch_gcs("auto") == ("Mission Planner", None)


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
