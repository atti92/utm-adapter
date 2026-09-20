from pathlib import Path
import importlib.util

import pytest


_MODULE_PATH = Path(__file__).parents[1] / "scripts" / "px4_sitl.py"
_SPEC = importlib.util.spec_from_file_location("px4_sitl", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

build_docker_command = _MODULE.build_docker_command
find_px4_binary = _MODULE.find_px4_binary


def test_build_docker_command_keeps_qgc_and_connector_on_px4_defaults() -> None:
    command = build_docker_command()

    assert command == [
        "docker",
        "run",
        "--rm",
        "--init",
        "-p",
        "14550:14550/udp",
        "-p",
        "14540:14540/udp",
        "-e",
        "PX4_SIM_MODEL=sihsim_quadx",
        "px4io/px4-sitl:latest",
    ]


def test_build_docker_command_supports_custom_host_ports_and_model() -> None:
    command = build_docker_command(
        "example/px4:test",
        model="sihsim_airplane",
        gcs_port=15000,
        connector_port=15001,
        container_name="utm-px4",
    )

    assert command == [
        "docker",
        "run",
        "--rm",
        "--init",
        "--name",
        "utm-px4",
        "-p",
        "15000:14550/udp",
        "-p",
        "15001:14540/udp",
        "-e",
        "PX4_SIM_MODEL=sihsim_airplane",
        "example/px4:test",
    ]


def test_find_px4_binary_reports_build_guidance(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Build PX4 with its documented SITL target"):
        find_px4_binary(tmp_path)


def test_find_px4_binary_accepts_sih_build(tmp_path: Path) -> None:
    binary = tmp_path / "build" / "px4_sitl_sih" / "bin" / "px4"
    binary.parent.mkdir(parents=True)
    binary.touch()

    assert find_px4_binary(tmp_path) == binary
