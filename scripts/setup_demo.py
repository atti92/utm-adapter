"""Prepare the cross-platform full-stack demo without overwriting checkouts.

The command installs the locked Python environment and clones only the
simulator/provider repositories that are missing. Existing directories are
validated and reused as-is, so local changes in a user's Flight Blender,
ArduPilot, or MAVLink Router checkout are never pulled, reset, or replaced.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ardupilot_sitl import find_copter_binary


DEFAULT_FLIGHT_BLENDER_ROOT = REPO_ROOT.parent / "flight-blender"
DEFAULT_ARDUPILOT_ROOT = REPO_ROOT.parent / "ardupilot"
DEFAULT_ROUTER_ROOT = REPO_ROOT.parent / "mavlink-router"


class DemoSetupError(RuntimeError):
    """Raised when the demo cannot be prepared safely."""


@dataclass(frozen=True)
class CheckoutSpec:
    label: str
    url: str
    path: Path
    required_files: tuple[str, ...]
    clone_flags: tuple[str, ...] = ()


def _configured_path(env_name: str, default: Path) -> Path:
    return Path(os.environ.get(env_name, str(default))).expanduser().resolve()


def _run(command: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(command), cwd=cwd, check=False, text=True)
    except OSError as exc:
        raise DemoSetupError(f"could not run {' '.join(command)}: {exc}") from exc


def _missing_files(spec: CheckoutSpec) -> list[str]:
    return [relative for relative in spec.required_files if not (spec.path / relative).is_file()]


def _validate_existing_checkout(spec: CheckoutSpec) -> None:
    if not spec.path.is_dir():
        raise DemoSetupError(
            f"{spec.label} path exists but is not a directory: {spec.path}; "
            "choose another path or move it aside before retrying"
        )
    missing = _missing_files(spec)
    if missing:
        joined = ", ".join(missing)
        raise DemoSetupError(
            f"{spec.label} directory does not look like a usable checkout: {spec.path} "
            f"(missing: {joined}); refusing to overwrite it"
        )


def ensure_checkout(spec: CheckoutSpec) -> str:
    """Ensure a checkout exists and return ``cloned`` or ``reused``.

    The function intentionally does not run ``git pull`` or mutate an existing
    directory. That makes it safe to use around user-maintained simulator
    branches and local patches.
    """

    if spec.path.exists():
        _validate_existing_checkout(spec)
        return "reused"

    if shutil.which("git") is None:
        raise DemoSetupError(
            f"git is required to clone {spec.label}; install Git or provide an existing "
            f"checkout at {spec.path}"
        )

    spec.path.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        ["git", "clone", "--depth", "1", *spec.clone_flags, spec.url, str(spec.path)]
    )
    if result.returncode != 0:
        raise DemoSetupError(
            f"could not clone {spec.label} from {spec.url}; fix the repository/network "
            "and run setup again"
        )
    try:
        _validate_existing_checkout(spec)
    except DemoSetupError as exc:
        raise DemoSetupError(
            f"the new {spec.label} clone is incomplete at {spec.path}: {exc}"
        ) from exc
    return "cloned"


def _sync_python_environment() -> None:
    if shutil.which("uv") is None:
        raise DemoSetupError(
            "uv is required; install it from https://docs.astral.sh/uv/ and run setup again"
        )
    result = _run(["uv", "sync", "--locked"], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise DemoSetupError("uv sync failed; see the output above for the dependency error")


def _check_ardupilot_submodules(root: Path) -> None:
    """Fail early when an existing ArduPilot checkout is not build-ready.

    Setup deliberately never initializes or updates an existing checkout. A
    clear preflight error is more useful than letting Waf fail much later with
    a missing generated dependency.
    """

    git = shutil.which("git")
    if git is None:
        raise DemoSetupError(
            "git is required to inspect the ArduPilot submodules; install Git and retry"
        )
    if not (root / ".gitmodules").is_file():
        raise DemoSetupError(
            f"ArduPilot checkout is missing .gitmodules: {root}; "
            "provide a complete checkout or choose another path"
        )
    try:
        result = subprocess.run(
            [git, "-C", str(root), "submodule", "status", "--recursive"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise DemoSetupError(f"could not inspect ArduPilot submodules: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise DemoSetupError(f"could not inspect ArduPilot submodules{suffix}")

    incomplete = [
        line.strip()
        for line in result.stdout.splitlines()
        if line[:1] in {"-", "U"}
    ]
    if incomplete:
        raise DemoSetupError(
            f"ArduPilot submodules are not initialized in {root}; run "
            f"git -C \"{root}\" submodule update --init --recursive, then retry "
            "(setup will not modify an existing checkout)"
        )


def _build_ardupilot(root: Path) -> None:
    try:
        binary = find_copter_binary(root)
    except FileNotFoundError:
        binary = None
    if binary is not None:
        print(f"[ok] ArduCopter SITL already built: {binary}")
        return

    waf = root / "waf"
    waf_bat = root / "waf.bat"
    if waf.is_file():
        waf_command = [sys.executable, str(waf)]
    elif waf_bat.is_file():
        waf_command = [str(waf_bat)]
    else:
        raise DemoSetupError(f"ArduPilot waf launcher was not found in {root}")

    print("[info] configuring ArduPilot SITL (this can take a few minutes)")
    result = _run([*waf_command, "configure", "--board", "sitl"], cwd=root)
    if result.returncode != 0:
        raise DemoSetupError("ArduPilot SITL configuration failed")
    print("[info] building ArduCopter SITL")
    result = _run([*waf_command, "copter", "-j2"], cwd=root)
    if result.returncode != 0:
        raise DemoSetupError("ArduCopter SITL build failed")
    try:
        binary = find_copter_binary(root)
    except FileNotFoundError as exc:
        raise DemoSetupError(str(exc)) from exc
    print(f"[ok] built ArduCopter SITL: {binary}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--simulator",
        choices=("ardupilot", "px4"),
        default="ardupilot",
        help="prepare ArduPilot or the Docker-only PX4 demo (default: ardupilot)",
    )
    parser.add_argument(
        "--topology",
        choices=("split", "router"),
        default="split",
        help="prepare the direct split or single-link router topology (default: split)",
    )
    parser.add_argument(
        "--flight-blender-root",
        type=Path,
        default=_configured_path("FLIGHT_BLENDER_ROOT", DEFAULT_FLIGHT_BLENDER_ROOT),
    )
    parser.add_argument(
        "--ardupilot-root",
        type=Path,
        default=_configured_path("ARDUPILOT_ROOT", DEFAULT_ARDUPILOT_ROOT),
    )
    parser.add_argument(
        "--router-source-root",
        type=Path,
        default=_configured_path("MAVLINK_ROUTER_ROOT", DEFAULT_ROUTER_ROOT),
    )
    parser.add_argument(
        "--build-ardupilot",
        action="store_true",
        help="build ArduCopter SITL after preparing the ArduPilot checkout",
    )
    parser.add_argument(
        "--skip-uv-sync",
        action="store_true",
        help="reuse the current Python environment without running uv sync --locked",
    )
    return parser


def _specs(args: argparse.Namespace) -> list[CheckoutSpec]:
    if args.build_ardupilot and args.simulator != "ardupilot":
        raise DemoSetupError("--build-ardupilot requires --simulator ardupilot")
    specs = [
        CheckoutSpec(
            "Flight Blender",
            "https://github.com/openutm/flight-blender.git",
            args.flight_blender_root.expanduser().resolve(),
            ("docker-compose-dev.yml",),
        )
    ]
    if args.simulator == "ardupilot":
        specs.append(
            CheckoutSpec(
                "ArduPilot",
                "https://github.com/ArduPilot/ardupilot.git",
                args.ardupilot_root.expanduser().resolve(),
                ("waf", "Tools/autotest/sim_vehicle.py"),
                ("--recurse-submodules", "--shallow-submodules"),
            )
        )
    if args.topology == "router":
        if args.simulator != "ardupilot":
            raise DemoSetupError("the router topology currently requires --simulator ardupilot")
        specs.append(
            CheckoutSpec(
                "MAVLink Router",
                "https://github.com/mavlink-router/mavlink-router.git",
                args.router_source_root.expanduser().resolve(),
                ("examples/Dockerfile.ubuntu",),
            )
        )
    return specs


def _check_command(args: argparse.Namespace) -> str:
    parts = [
        "uv run python scripts/check_demo.py",
        f"--simulator {args.simulator}",
        f"--topology {args.topology}",
        f'--flight-blender-root "{args.flight_blender_root.expanduser().resolve()}"',
    ]
    if args.simulator == "ardupilot":
        parts.append(f'--ardupilot-root "{args.ardupilot_root.expanduser().resolve()}"')
    if args.topology == "router":
        parts.append(f'--router-source-root "{args.router_source_root.expanduser().resolve()}"')
    return " ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.skip_uv_sync:
            print("[info] syncing the locked Python environment")
            _sync_python_environment()
            print("[ok] Python environment ready")

        for spec in _specs(args):
            state = ensure_checkout(spec)
            print(f"[ok] {spec.label} {state}: {spec.path}")

        if args.build_ardupilot:
            _check_ardupilot_submodules(args.ardupilot_root.expanduser().resolve())
            _build_ardupilot(args.ardupilot_root.expanduser().resolve())
        elif args.simulator == "ardupilot":
            print(
                "[info] ArduPilot was not built by setup; add --build-ardupilot or run "
                "the waf commands shown by demo-check"
            )
    except DemoSetupError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print("\nNext steps")
    print("----------")
    print(f"1. Run: {_check_command(args)}")
    if args.simulator == "ardupilot" and not args.build_ardupilot:
        ardupilot_root = args.ardupilot_root.expanduser().resolve()
        if os.name == "nt":
            print(
                f'2. If ArduPilot is not built, run: Set-Location "{ardupilot_root}"; '
                "python waf configure --board sitl; python waf copter -j2"
            )
        else:
            print(
                f'2. If ArduPilot is not built, run: cd "{ardupilot_root}" '
                "&& ./waf configure --board sitl && ./waf copter -j2"
            )
        print("3. Start the operator-facing demo with: uv run python scripts/openutm_demo.py --gcs auto")
    else:
        print("2. Start the operator-facing demo with: uv run python scripts/openutm_demo.py --gcs auto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
