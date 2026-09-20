from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts import setup_demo


def _valid_checkout(tmp_path: Path, *required_files: str) -> Path:
    root = tmp_path / "checkout"
    for relative in required_files:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    return root


def test_existing_checkout_is_reused_without_running_git(tmp_path: Path, monkeypatch) -> None:
    root = _valid_checkout(tmp_path, "docker-compose-dev.yml")
    observed: list[list[str]] = []
    monkeypatch.setattr(setup_demo, "_run", lambda command, **_kwargs: observed.append(list(command)))

    spec = setup_demo.CheckoutSpec("Flight Blender", "unused", root, ("docker-compose-dev.yml",))

    assert setup_demo.ensure_checkout(spec) == "reused"
    assert observed == []


def test_existing_incomplete_directory_is_never_overwritten(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "flight-blender"
    root.mkdir()
    observed: list[list[str]] = []
    monkeypatch.setattr(setup_demo, "_run", lambda command, **_kwargs: observed.append(list(command)))

    spec = setup_demo.CheckoutSpec("Flight Blender", "unused", root, ("docker-compose-dev.yml",))

    with pytest.raises(setup_demo.DemoSetupError, match="refusing to overwrite"):
        setup_demo.ensure_checkout(spec)
    assert observed == []


def test_missing_checkout_clones_shallow_repository(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "flight-blender"
    observed: list[list[str]] = []

    def fake_run(command, **_kwargs):
        observed.append(list(command))
        root.mkdir()
        (root / "docker-compose-dev.yml").touch()
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(setup_demo, "_run", fake_run)
    monkeypatch.setattr(setup_demo.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    spec = setup_demo.CheckoutSpec(
        "Flight Blender", "https://example.test/flight-blender.git", root, ("docker-compose-dev.yml",)
    )

    assert setup_demo.ensure_checkout(spec) == "cloned"
    assert observed == [["git", "clone", "--depth", "1", spec.url, str(root)]]


def test_setup_parser_can_select_px4_without_router() -> None:
    args = setup_demo._parser().parse_args(["--simulator", "px4", "--skip-uv-sync"])

    assert args.simulator == "px4"
    assert args.topology == "split"
    assert args.skip_uv_sync is True
    assert [spec.label for spec in setup_demo._specs(args)] == ["Flight Blender"]


def test_router_setup_rejects_px4() -> None:
    args = setup_demo._parser().parse_args(
        ["--simulator", "px4", "--topology", "router", "--skip-uv-sync"]
    )

    with pytest.raises(setup_demo.DemoSetupError, match="requires --simulator ardupilot"):
        setup_demo._specs(args)


def test_ardupilot_build_flag_rejects_px4() -> None:
    args = setup_demo._parser().parse_args(
        ["--simulator", "px4", "--build-ardupilot", "--skip-uv-sync"]
    )

    with pytest.raises(setup_demo.DemoSetupError, match="--build-ardupilot"):
        setup_demo._specs(args)


def test_check_command_includes_custom_checkout_paths(tmp_path: Path) -> None:
    args = setup_demo._parser().parse_args(
        [
            "--flight-blender-root",
            str(tmp_path / "flight blender"),
            "--ardupilot-root",
            str(tmp_path / "ardupilot"),
            "--topology",
            "router",
            "--router-source-root",
            str(tmp_path / "router"),
        ]
    )

    command = setup_demo._check_command(args)

    assert f'"{tmp_path}' in command
    assert "--topology router" in command
    assert "--router-source-root" in command
