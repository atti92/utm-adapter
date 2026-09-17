import socket

from utm_connector.diagnostics import port_is_reachable


def test_doctor_detects_an_active_listen_port() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        assert port_is_reachable("127.0.0.1", listener.getsockname()[1]) is True
    finally:
        listener.close()
