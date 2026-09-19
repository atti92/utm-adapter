from pathlib import Path
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
    assert config.connector_record_path == config.run_dir / "connector-events.jsonl"


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


def test_qgroundcontrol_detection_is_optional_for_auto_mode(monkeypatch) -> None:
    monkeypatch.setattr(openutm_demo, "_find_qgroundcontrol_command", lambda: None)

    assert openutm_demo._launch_gcs("auto") is None


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
