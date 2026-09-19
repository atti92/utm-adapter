from pathlib import Path
import importlib.util

import pytest


_MODULE_PATH = Path(__file__).parents[1] / "scripts" / "ardupilot_sitl.py"
_SPEC = importlib.util.spec_from_file_location("ardupilot_sitl", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

build_command = _MODULE.build_command
find_copter_binary = _MODULE.find_copter_binary


def test_build_command_uses_two_independent_udp_outputs() -> None:
    command = build_command(
        Path("/tmp/arducopter"),
        home="1,2,3,4",
        model="quad",
        gcs_port=15000,
        connector_port=15001,
    )

    assert command == [
        "/tmp/arducopter",
        "--model",
        "quad",
        "--home",
        "1,2,3,4",
        "--serial0",
        "udpclient:127.0.0.1:15000",
        "--serial1",
        "udpclient:127.0.0.1:15001",
    ]


def test_find_copter_binary_reports_build_guidance(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Build it in the ArduPilot checkout"):
        find_copter_binary(tmp_path)


def test_find_copter_binary_accepts_built_binary(tmp_path: Path) -> None:
    binary = tmp_path / "build" / "sitl" / "bin" / "arducopter"
    binary.parent.mkdir(parents=True)
    binary.touch()

    assert find_copter_binary(tmp_path) == binary
