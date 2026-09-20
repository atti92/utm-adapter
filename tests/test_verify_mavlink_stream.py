from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.verify_mavlink_stream import (
    MavlinkStreamVerificationError,
    verify_mavlink_stream,
)


class FakeMessage:
    def get_srcSystem(self) -> int:
        return 42

    def get_srcComponent(self) -> int:
        return 1


class FakeConnection:
    def __init__(self, message=None) -> None:
        self.message = message
        self.closed = False

    def recv_match(self, **_kwargs):
        return self.message

    def close(self) -> None:
        self.closed = True


def test_verify_mavlink_stream_reads_heartbeat_and_closes_connection(monkeypatch) -> None:
    connection = FakeConnection(FakeMessage())
    observed = {}

    def fake_connection(uri, **kwargs):
        observed["uri"] = uri
        observed["kwargs"] = kwargs
        return connection

    monkeypatch.setattr(
        "scripts.verify_mavlink_stream.mavutil.mavlink_connection",
        fake_connection,
    )

    result = verify_mavlink_stream("127.0.0.1", 14550, timeout_s=1)

    assert result.system_id == 42
    assert result.component_id == 1
    assert observed == {
        "uri": "udpin:127.0.0.1:14550",
        "kwargs": {"autoreconnect": False, "udp_timeout": 1.0},
    }
    assert connection.closed is True


def test_verify_mavlink_stream_reports_timeout_and_closes_connection(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        "scripts.verify_mavlink_stream.mavutil.mavlink_connection",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(MavlinkStreamVerificationError, match="no vehicle heartbeat"):
        verify_mavlink_stream("127.0.0.1", 14550, timeout_s=0.05)

    assert connection.closed is True


def test_verify_mavlink_stream_rejects_invalid_port() -> None:
    with pytest.raises(ValueError, match="between 1 and 65535"):
        verify_mavlink_stream("127.0.0.1", 0)
