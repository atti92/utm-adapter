from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts import check_mavlink_router
from scripts.check_mavlink_router import DEFAULT_CONFIG, validate


def test_checked_in_router_config_matches_gcs_and_connector_fanout() -> None:
    assert validate(DEFAULT_CONFIG) == []


def test_router_config_rejects_duplicate_consumer_port(tmp_path: Path) -> None:
    config = tmp_path / "main.conf"
    config.write_text(
        """[General]
TcpServerPort = 5760

[UdpEndpoint qgroundcontrol]
Mode = Normal
Address = 127.0.0.1
Port = 14550

[UdpEndpoint utm_connector]
Mode = Normal
Address = 127.0.0.1
Port = 14550

[UdpEndpoint vehicle_input]
Mode = Server
Address = 0.0.0.0
Port = 14560
""",
        encoding="utf-8",
    )

    errors = validate(config)

    assert any("used by both" in error for error in errors)


def test_router_config_rejects_missing_vehicle_server(tmp_path: Path) -> None:
    config = tmp_path / "main.conf"
    config.write_text(
        """[General]
TcpServerPort = 5760

[UdpEndpoint qgroundcontrol]
Mode = Normal
Address = 127.0.0.1
Port = 14550

[UdpEndpoint utm_connector]
Mode = Normal
Address = 127.0.0.1
Port = 14551
""",
        encoding="utf-8",
    )

    errors = validate(config)

    assert "missing [UdpEndpoint vehicle_input] section" in errors


def test_router_runtime_auto_accepts_docker_source_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_root = tmp_path / "mavlink-router"
    dockerfile = source_root / "examples" / "Dockerfile.ubuntu"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr(check_mavlink_router, "_router_binary", lambda: None)
    monkeypatch.setattr(check_mavlink_router, "_docker_available", lambda: (True, ""))
    monkeypatch.setattr(check_mavlink_router, "_docker_image_is_available", lambda _image: False)

    assert check_mavlink_router._select_runtime("auto", source_root, "router:test") == "docker"


def test_router_strict_accepts_docker_source_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "mavlink-router"
    dockerfile = source_root / "examples" / "Dockerfile.ubuntu"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr(check_mavlink_router, "_router_binary", lambda: None)
    monkeypatch.setattr(check_mavlink_router, "_docker_available", lambda: (True, ""))
    monkeypatch.setattr(check_mavlink_router, "_docker_image_is_available", lambda _image: False)

    result = check_mavlink_router.main(
        [
            "--strict",
            "--router-source-root",
            str(source_root),
            "--router-image",
            "router:test",
        ]
    )

    assert result == 0
    assert "Docker MAVLink Router fallback" in capsys.readouterr().out


def test_router_strict_fails_without_native_or_docker_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(check_mavlink_router, "_router_binary", lambda: None)
    monkeypatch.setattr(check_mavlink_router, "_docker_available", lambda: (False, "daemon unavailable"))

    result = check_mavlink_router.main(
        ["--strict", "--router-source-root", str(tmp_path / "missing")]
    )

    assert result == 1
