from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

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
