"""Start a complete local Flight Blender + SITL + connector demo.

The launcher owns only the processes it starts. It is intentionally a small
Python supervisor instead of a shell script so the same workflow works from
macOS, Linux, WSL, and Windows PowerShell. The normal operator interaction
remains in the browser console and the selected GCS; the terminal is only used
to show startup logs and to stop the demo with Ctrl+C.
"""

from __future__ import annotations

import argparse
import ipaddress
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ardupilot_sitl import DEFAULT_HOME, find_copter_binary
from scripts import check_mavlink_router
from scripts.generate_flight_blender_dev_token import generate_token
from scripts.generate_test_mission import write_demo_mission_files
from scripts.px4_sitl import (
    DEFAULT_DOCKER_IMAGE as DEFAULT_PX4_IMAGE,
    DEFAULT_GCS_PORT as DEFAULT_PX4_GCS_PORT,
    DEFAULT_CONNECTOR_PORT as DEFAULT_PX4_CONNECTOR_PORT,
)
from utm_connector.diagnostics import (
    port_is_reachable,
    probe_http_endpoint,
    udp_port_is_available,
)
from scripts.verify_running_demo import (
    MISSION_FORMATS,
    DemoVerificationError,
    verify_running_demo,
)
from scripts.verify_mavlink_stream import (
    MavlinkStreamVerificationError,
    verify_mavlink_stream,
)


DEFAULT_VEHICLE_ID = "sitl-1"
DEFAULT_PROVIDER_PORT = 8000
DEFAULT_CONNECTOR_PORT = 8001
DEFAULT_GCS_UDP_PORT = 14550
DEFAULT_CONNECTOR_UDP_PORT = 14551
DEFAULT_ROUTER_INPUT_PORT = 14560
DEFAULT_ROUTER_CONFIG = REPO_ROOT / "examples" / "mavlink-router" / "main.conf"
DEFAULT_ROUTER_RUNTIME = "auto"
DEFAULT_ROUTER_IMAGE = "utm-adapter-mavlink-router:local"
DEFAULT_PROVIDER_TIMEOUT_S = 180.0
DEFAULT_CONNECTOR_TIMEOUT_S = 30.0
FLIGHT_BLENDER_IMAGE = "openutm/flight-blender-dev"


class DemoSetupError(RuntimeError):
    """Raised when the local full-stack demo cannot be started safely."""


@dataclass(frozen=True)
class DemoConfig:
    adapter_root: Path = REPO_ROOT
    flight_blender_root: Path = REPO_ROOT.parent / "flight-blender"
    ardupilot_root: Path = REPO_ROOT.parent / "ardupilot"
    simulator: str = "ardupilot"
    topology: str = "split"
    px4_image: str = DEFAULT_PX4_IMAGE
    home: str = DEFAULT_HOME
    vehicle_id: str = DEFAULT_VEHICLE_ID
    provider_port: int = DEFAULT_PROVIDER_PORT
    connector_port: int = DEFAULT_CONNECTOR_PORT
    gcs_udp_port: int = DEFAULT_GCS_UDP_PORT
    connector_udp_port: int = DEFAULT_CONNECTOR_UDP_PORT
    router_config: Path = DEFAULT_ROUTER_CONFIG
    router_port: int = DEFAULT_ROUTER_INPUT_PORT
    router_runtime: str = DEFAULT_ROUTER_RUNTIME
    router_source_root: Path = REPO_ROOT.parent / "mavlink-router"
    router_image: str = DEFAULT_ROUTER_IMAGE
    provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S
    connector_timeout_s: float = DEFAULT_CONNECTOR_TIMEOUT_S
    gcs: str = "auto"
    qgroundcontrol_command: tuple[str, ...] | None = None
    open_browser: bool = True
    keep_provider: bool = False
    verify: bool = False
    verify_mission_format: str = "canonical"

    @property
    def provider_url(self) -> str:
        return f"http://127.0.0.1:{self.provider_port}"

    @property
    def connector_url(self) -> str:
        return f"http://127.0.0.1:{self.connector_port}"

    @property
    def run_dir(self) -> Path:
        return self.adapter_root / ".local" / "openutm-demo"

    @property
    def connector_record_path(self) -> Path:
        return self.run_dir / "connector-events.jsonl"

    @property
    def px4_container_name(self) -> str:
        safe_vehicle_id = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in self.vehicle_id
        )
        return f"utm-adapter-px4-{safe_vehicle_id}"

    @property
    def router_container_name(self) -> str:
        safe_vehicle_id = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in self.vehicle_id
        )
        return f"utm-adapter-router-{safe_vehicle_id}"


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[bytes]
    log_file: object

    def stop(self) -> None:
        if self.process.poll() is not None:
            self.log_file.close()
            return

        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        finally:
            self.log_file.close()


@dataclass
class ManagedApplication:
    """Own a native app launched through a platform app launcher.

    macOS ``open -a`` returns after handing the app to LaunchServices, so the
    launcher process is not a useful child to reap.  Keep an explicit cleanup
    action instead, and only create this resource when the app was not already
    running before the demo started.
    """

    name: str
    stop_command: tuple[str, ...]

    def stop(self) -> None:
        if not _gcs_process_is_running(self.name):
            return
        _run_command(list(self.stop_command), capture_output=True)


DEMO_ARTIFACTS = (
    "connector-events.jsonl",
    "connector.log",
    "mission-planner.waypoints",
    "mavlink-router.log",
    "mission-qgroundcontrol.plan",
    "mission.json",
    "mission-planner.log",
    "qgroundcontrol.log",
    "sitl.log",
)


def _prepare_run_dir(run_dir: Path) -> None:
    """Start a demo with bounded, current-run diagnostics.

    The supervised launcher owns this directory.  Reset only its known output
    files so repeated simulator runs cannot append indefinitely to a stale
    MAVLink/SITL log or recorder file.
    """

    run_dir.mkdir(parents=True, exist_ok=True)
    for artifact in DEMO_ARTIFACTS:
        (run_dir / artifact).unlink(missing_ok=True)


def _parse_demo_home(home: str) -> tuple[float, float, float]:
    """Return the numeric lat/lon/altitude shared by SITL and demo files."""

    fields = [field.strip() for field in home.split(",")]
    if len(fields) < 3:
        raise ValueError("home must be lat,lon,altitude[,heading]")
    try:
        latitude, longitude, altitude = (float(value) for value in fields[:3])
    except ValueError as exc:
        raise ValueError("home latitude, longitude, and altitude must be numeric") from exc
    if not all(math.isfinite(value) for value in (latitude, longitude, altitude)):
        raise ValueError("home coordinates must be finite")
    if not -90 <= latitude <= 90:
        raise ValueError("home latitude must be between -90 and 90 degrees")
    if not -180 <= longitude <= 180:
        raise ValueError("home longitude must be between -180 and 180 degrees")
    return latitude, longitude, altitude


def _default_checkout(env_name: str, sibling_name: str) -> Path:
    configured = os.environ.get(env_name)
    if configured:
        return Path(configured).expanduser()
    return REPO_ROOT.parent / sibling_name


def _find_geoid_grid() -> Path | None:
    configured = os.environ.get("UTM_CONNECTOR_ALTITUDE_GEOID_GRID_PATH")
    if configured:
        return Path(configured).expanduser()

    candidates = [
        Path("/usr/share/proj/us_nga_egm96_15.tif"),
        Path("/opt/homebrew/share/proj/us_nga_egm96_15.tif"),
        Path("/usr/local/share/proj/us_nga_egm96_15.tif"),
    ]
    try:
        from pyproj import datadir

        data_dir = Path(datadir.get_data_dir())
        candidates.extend(
            [
                data_dir / "us_nga_egm96_15.tif",
                data_dir / "proj" / "us_nga_egm96_15.tif",
            ]
        )
        candidates.extend(data_dir.parent.glob("**/us_nga_egm96_15.tif"))
    except Exception:
        pass

    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _compose_base_command(config: DemoConfig) -> list[str]:
    compose_file = config.flight_blender_root / "docker-compose-dev.yml"
    return ["docker", "compose", "-f", str(compose_file)]


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = True,
    start_new_session: bool = False,
    timeout_s: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        text=True,
        capture_output=capture_output,
        start_new_session=start_new_session,
        timeout=timeout_s,
    )


def _command_available(command: Sequence[str]) -> tuple[bool, str]:
    try:
        result = _run_command(command)
    except OSError as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, (result.stdout or result.stderr).strip()
    return False, (result.stderr or result.stdout).strip()


def _ensure_provider_env(flight_blender_root: Path) -> bool:
    env_path = flight_blender_root / ".env"
    template_path = flight_blender_root / "deployment_support" / ".env.local"
    if env_path.exists():
        return False
    if not template_path.is_file():
        raise DemoSetupError(
            f"Flight Blender local environment template is missing: {template_path}"
        )
    shutil.copyfile(template_path, env_path)
    return True


def _compose_is_running(config: DemoConfig) -> bool:
    result = _run_command(
        [*_compose_base_command(config), "ps", "--status", "running", "-q"],
        cwd=config.flight_blender_root,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _provider_image_is_available() -> bool:
    result = _run_command(["docker", "image", "inspect", FLIGHT_BLENDER_IMAGE])
    return result.returncode == 0


def _provider_endpoint_is_ready(config: DemoConfig) -> bool:
    if not port_is_reachable("127.0.0.1", config.provider_port):
        return False
    ready, _detail = probe_http_endpoint(config.provider_url)
    return ready


def _compose_up_command(config: DemoConfig, *, compose_running: bool) -> list[str]:
    command = [*_compose_base_command(config), "up", "-d"]
    if not compose_running and not _provider_image_is_available():
        command.append("--build")
    return command


def _wait_for_http(url: str, timeout_s: float, *, path: str = "/ping") -> None:
    deadline = time.monotonic() + timeout_s
    last_detail = "not checked"
    while time.monotonic() < deadline:
        ok, detail = probe_http_endpoint(url, path=path)
        if ok:
            return
        last_detail = detail
        time.sleep(1.0)
    raise DemoSetupError(f"{url}{path} did not become ready: {last_detail}")


def _start_new_process(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> ManagedProcess:
    log_file = log_path.open("wb")
    popen_kwargs: dict[str, object] = {
        "cwd": cwd,
        "env": env,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(list(command), **popen_kwargs)
    except Exception:
        log_file.close()
        raise
    return ManagedProcess(name, process, log_file)


def _find_path_command(names: Sequence[str]) -> list[str] | None:
    for name in names:
        executable = shutil.which(name)
        if executable:
            return [executable]
    return None


def _find_router_command() -> str | None:
    """Find the native MAVLink Router executable for a router-backed demo."""

    configured = os.environ.get("MAVLINK_ROUTERD")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which("mavlink-routerd")


def _router_image_is_available(config: DemoConfig) -> bool:
    result = _run_command(["docker", "image", "inspect", config.router_image])
    return result.returncode == 0


def _router_docker_prerequisite_error(config: DemoConfig) -> str | None:
    """Return why the Docker router fallback cannot run, if applicable."""

    docker_ok, docker_detail = _command_available(["docker", "version"])
    if not docker_ok:
        return f"Docker is unavailable for the router fallback: {docker_detail or 'command failed'}"
    if _router_image_is_available(config):
        return None
    if not config.router_source_root.is_dir():
        return (
            "MAVLink Router source checkout not found for the Docker fallback: "
            f"{config.router_source_root} (set MAVLINK_ROUTER_ROOT)"
        )
    dockerfile = config.router_source_root / "examples" / "Dockerfile.ubuntu"
    if not dockerfile.is_file():
        return f"MAVLink Router Dockerfile not found: {dockerfile}"
    return None


def _select_router_runtime(config: DemoConfig) -> str | None:
    """Select native router first, then the portable Docker fallback."""

    if config.router_runtime == "native":
        return "native" if _find_router_command() else None
    if config.router_runtime == "docker":
        return "docker" if _router_docker_prerequisite_error(config) is None else None
    if config.router_runtime != "auto":
        return None
    if _find_router_command():
        return "native"
    return "docker" if _router_docker_prerequisite_error(config) is None else None


def _docker_router_host_ip(config: DemoConfig) -> str:
    """Resolve Docker's host-gateway to the numeric IPv4 form the router accepts."""

    configured = os.environ.get("MAVLINK_ROUTER_DOCKER_HOST")
    if configured:
        try:
            address = ipaddress.ip_address(configured.strip())
        except ValueError as exc:
            raise DemoSetupError(
                f"MAVLINK_ROUTER_DOCKER_HOST must be an IP address (got {configured!r})"
            ) from exc
        if address.version != 4:
            raise DemoSetupError("MAVLINK_ROUTER_DOCKER_HOST must be an IPv4 address")
        return str(address)

    result = _run_command(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            "--add-host",
            "host.docker.internal:host-gateway",
            config.router_image,
            "-c",
            "awk '$2 == \"host.docker.internal\" { print $1; exit }' /etc/hosts",
        ]
    )
    candidate = result.stdout.strip().splitlines()
    if result.returncode != 0 or not candidate:
        raise DemoSetupError(
            "Docker could not resolve host-gateway for the router; set "
            "MAVLINK_ROUTER_DOCKER_HOST to the host IPv4 address"
        )
    try:
        address = ipaddress.ip_address(candidate[-1].strip())
    except ValueError as exc:
        raise DemoSetupError(
            f"Docker returned an invalid host-gateway address: {candidate[-1]!r}"
        ) from exc
    if address.version != 4:
        raise DemoSetupError("Docker host-gateway resolved to IPv6; set MAVLINK_ROUTER_DOCKER_HOST")
    return str(address)


def _find_windows_installed_command(relative_paths: Sequence[str]) -> list[str] | None:
    roots = (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    )
    for root in roots:
        if not root:
            continue
        for relative_path in relative_paths:
            executable = Path(root) / relative_path
            if executable.is_file():
                return [str(executable)]
    return None


def _find_qgroundcontrol_command() -> list[str] | None:
    if sys.platform == "darwin":
        for app_root in (Path("/Applications"), Path.home() / "Applications"):
            executable = app_root / "QGroundControl.app" / "Contents" / "MacOS" / "QGroundControl"
            if executable.is_file() and os.access(executable, os.X_OK):
                return [str(executable)]
        available, _detail = _command_available(["open", "-Ra", "QGroundControl"])
        return ["open", "-a", "QGroundControl"] if available else None
    if os.name == "nt":
        installed = _find_windows_installed_command(
            (
                "QGroundControl/QGroundControl.exe",
                "QGroundControl/qgroundcontrol.exe",
            )
        )
        return installed or _find_path_command(("QGroundControl.exe", "qgroundcontrol.exe"))
    return _find_path_command(("qgroundcontrol", "QGroundControl"))


def _parse_command_override(value: str) -> tuple[str, ...]:
    """Parse a user-provided executable plus optional arguments."""

    try:
        command = tuple(shlex.split(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid command quoting: {exc}") from exc
    if not command:
        raise argparse.ArgumentTypeError("the command must not be empty")
    return command


def _find_mission_planner_command() -> list[str] | None:
    if os.name != "nt":
        return None
    installed = _find_windows_installed_command(
        (
            "Mission Planner/MissionPlanner.exe",
            "MissionPlanner/MissionPlanner.exe",
        )
    )
    return installed or _find_path_command(("MissionPlanner.exe", "missionplanner.exe"))


def _launch_gcs(
    selection: str,
    *,
    run_dir: Path | None = None,
    qgroundcontrol_command: Sequence[str] | None = None,
) -> tuple[str | None, ManagedProcess | ManagedApplication | None]:
    if selection == "none":
        return None, None
    if selection == "auto":
        candidates = (
            (
                "QGroundControl",
                list(qgroundcontrol_command) if qgroundcontrol_command else _find_qgroundcontrol_command(),
            ),
            ("Mission Planner", _find_mission_planner_command()),
        )
        label, command = next(
            (
                (candidate_label, candidate_command)
                for candidate_label, candidate_command in candidates
                if candidate_command
            ),
            ("QGroundControl or Mission Planner", None),
        )
    elif selection == "mission-planner":
        command = _find_mission_planner_command()
        label = "Mission Planner"
    else:
        command = (
            list(qgroundcontrol_command)
            if qgroundcontrol_command
            else _find_qgroundcontrol_command()
        )
        label = "QGroundControl"
    if command is None:
        if selection == "auto":
            print("[info] no supported GCS was found; open QGroundControl or Mission Planner manually")
            return None, None
        raise DemoSetupError(f"{label} was requested but was not found on this host")

    managed: ManagedProcess | ManagedApplication | None = None
    app_launcher = sys.platform == "darwin" and command[:1] == ["open"]
    app_was_running = _gcs_process_is_running(label) if app_launcher else False
    if run_dir is not None and not app_launcher:
        managed = _start_new_process(
            label,
            command,
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            log_path=run_dir / ("qgroundcontrol.log" if label == "QGroundControl" else "mission-planner.log"),
        )
    else:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if app_launcher:
            if run_dir is not None and not app_was_running:
                managed = ManagedApplication(
                    name=label,
                    stop_command=(
                        "osascript",
                        "-e",
                        'tell application "QGroundControl" to quit',
                    ),
                )
                print("[info] QGroundControl was not running before this demo; cleanup will close it")
            else:
                print("[info] macOS app launcher used; the pre-existing GCS process is not owned by this run")
    print(f"[ok] launched {label}")
    return label, managed


def _gcs_process_is_running(label: str) -> bool:
    """Return whether a selected native GCS process is visible on this host."""

    if label == "QGroundControl":
        names = ("QGroundControl", "qgroundcontrol", "QGroundControl.exe")
    elif label == "Mission Planner":
        names = ("MissionPlanner.exe", "missionplanner.exe")
    else:  # pragma: no cover - labels are produced by _launch_gcs
        return False

    if os.name == "nt":
        for name in names:
            result = _run_command(
                ["tasklist", "/FI", f"IMAGENAME eq {name}"],
                capture_output=True,
            )
            if result.returncode == 0 and name.lower() in result.stdout.lower():
                return True
        return False

    for name in names:
        result = _run_command(["pgrep", "-x", name], capture_output=True)
        if result.returncode == 0 and result.stdout.strip():
            return True
    return False


def _wait_for_gcs(
    label: str,
    managed: ManagedProcess | ManagedApplication | None,
    *,
    timeout_s: float = 10.0,
    log_path: Path | None = None,
) -> None:
    """Confirm that the requested GCS process is alive after launch."""

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        process = getattr(managed, "process", None)
        if process is not None and process.poll() is None:
            print(f"[ok] {label} process is running")
            return
        if _gcs_process_is_running(label):
            print(f"[ok] {label} process is running")
            return
        time.sleep(0.25)

    detail = f"; inspect {log_path}" if log_path is not None else ""
    raise DemoSetupError(f"{label} did not stay running after launch{detail}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start Flight Blender, SITL, the UTM connector, and the operator console"
    )
    parser.add_argument(
        "--simulator",
        choices=("ardupilot", "px4"),
        default="ardupilot",
        help="SITL implementation (default: ardupilot; PX4 uses its official Docker image)",
    )
    parser.add_argument(
        "--topology",
        choices=("split", "router"),
        default="split",
        help=(
            "MAVLink wiring: split sends directly to GCS and connector; router "
            "uses one ArduPilot output and mavlink-routerd fan-out"
        ),
    )
    parser.add_argument(
        "--flight-blender-root",
        type=Path,
        default=_default_checkout("FLIGHT_BLENDER_ROOT", "flight-blender"),
    )
    parser.add_argument(
        "--ardupilot-root",
        type=Path,
        default=_default_checkout("ARDUPILOT_ROOT", "ardupilot"),
    )
    parser.add_argument(
        "--px4-image",
        default=os.environ.get("PX4_SITL_IMAGE", DEFAULT_PX4_IMAGE),
        help=f"PX4 SITL container image (default: {DEFAULT_PX4_IMAGE})",
    )
    parser.add_argument("--home", default=DEFAULT_HOME, help="lat,lon,altitude,heading")
    parser.add_argument("--vehicle-id", default=DEFAULT_VEHICLE_ID)
    parser.add_argument("--provider-port", type=int, default=DEFAULT_PROVIDER_PORT)
    parser.add_argument("--connector-port", type=int, default=DEFAULT_CONNECTOR_PORT)
    parser.add_argument(
        "--gcs-udp-port",
        type=int,
        default=DEFAULT_GCS_UDP_PORT,
        help="SITL UDP output for QGroundControl or Mission Planner (default: 14550)",
    )
    parser.add_argument(
        "--connector-udp-port",
        type=int,
        default=None,
        help=(
            "SITL UDP input consumed by the connector "
            "(default: 14551 for ArduPilot, 14540 for PX4; stock PX4 requires 14540)"
        ),
    )
    parser.add_argument(
        "--router-config",
        type=Path,
        default=Path(os.environ.get("MAVLINK_ROUTER_CONFIG", DEFAULT_ROUTER_CONFIG)),
        help="mavlink-routerd configuration for --topology router",
    )
    parser.add_argument(
        "--router-runtime",
        choices=("auto", "native", "docker"),
        default=os.environ.get("MAVLINK_ROUTER_RUNTIME", DEFAULT_ROUTER_RUNTIME),
        help=(
            "router process runtime: native mavlink-routerd, Docker fallback, "
            "or auto-select native then Docker (default: auto)"
        ),
    )
    parser.add_argument(
        "--router-source-root",
        type=Path,
        default=_default_checkout("MAVLINK_ROUTER_ROOT", "mavlink-router"),
        help="MAVLink Router checkout used to build the Docker fallback",
    )
    parser.add_argument(
        "--router-image",
        default=os.environ.get("MAVLINK_ROUTER_IMAGE", DEFAULT_ROUTER_IMAGE),
        help=f"Docker router image (default: {DEFAULT_ROUTER_IMAGE})",
    )
    parser.add_argument("--provider-timeout", type=float, default=DEFAULT_PROVIDER_TIMEOUT_S)
    parser.add_argument("--connector-timeout", type=float, default=DEFAULT_CONNECTOR_TIMEOUT_S)
    parser.add_argument(
        "--gcs",
        choices=("auto", "none", "qgroundcontrol", "mission-planner"),
        default="auto",
        help="launch a GCS after the vehicle is online (default: auto-detect QGroundControl, then Mission Planner)",
    )
    parser.add_argument(
        "--qgroundcontrol-command",
        type=_parse_command_override,
        default=os.environ.get("QGROUNDCONTROL_COMMAND"),
        help=(
            "custom QGroundControl executable and optional arguments; useful for a "
            "locally built app (also via QGROUNDCONTROL_COMMAND)"
        ),
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open the operator console")
    parser.add_argument(
        "--keep-provider",
        action="store_true",
        help="leave the Flight Blender Compose stack running after Ctrl+C",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="run the browser-console lifecycle check after startup, then exit",
    )
    parser.add_argument(
        "--verify-mission-format",
        choices=MISSION_FORMATS,
        default="canonical",
        help=(
            "mission upload path used by --verify: canonical, qgroundcontrol, "
            "or mission-planner (default: canonical)"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only validate prerequisites; do not start Docker, SITL, or the connector",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> DemoConfig:
    connector_udp_port = args.connector_udp_port
    if connector_udp_port is None:
        connector_udp_port = (
            DEFAULT_PX4_CONNECTOR_PORT
            if args.simulator == "px4"
            else DEFAULT_CONNECTOR_UDP_PORT
        )
    return DemoConfig(
        adapter_root=REPO_ROOT,
        flight_blender_root=args.flight_blender_root.expanduser().resolve(),
        ardupilot_root=args.ardupilot_root.expanduser().resolve(),
        simulator=args.simulator,
        topology=args.topology,
        px4_image=args.px4_image,
        home=args.home,
        vehicle_id=args.vehicle_id,
        provider_port=args.provider_port,
        connector_port=args.connector_port,
        gcs_udp_port=args.gcs_udp_port,
        connector_udp_port=connector_udp_port,
        router_config=args.router_config.expanduser().resolve(),
        router_port=DEFAULT_ROUTER_INPUT_PORT,
        router_runtime=args.router_runtime,
        router_source_root=args.router_source_root.expanduser().resolve(),
        router_image=args.router_image,
        provider_timeout_s=args.provider_timeout,
        connector_timeout_s=args.connector_timeout,
        gcs=args.gcs,
        qgroundcontrol_command=(
            tuple(args.qgroundcontrol_command)
            if args.qgroundcontrol_command
            else None
        ),
        open_browser=not args.no_browser,
        keep_provider=args.keep_provider,
        verify=args.verify,
        verify_mission_format=args.verify_mission_format,
    )


def check_prerequisites(config: DemoConfig) -> list[str]:
    """Return human-readable prerequisite failures without starting anything."""

    failures: list[str] = []
    try:
        _parse_demo_home(config.home)
    except ValueError as exc:
        failures.append(str(exc))
    for label, port in (
        ("Flight Blender HTTP port", config.provider_port),
        ("connector HTTP port", config.connector_port),
    ):
        if not 1 <= port <= 65535:
            failures.append(f"{label} must be between 1 and 65535 (got {port})")
    if config.provider_port == config.connector_port:
        failures.append("Flight Blender HTTP port and connector HTTP port must be different")

    for label, port in (
        ("GCS UDP port", config.gcs_udp_port),
        ("connector UDP port", config.connector_udp_port),
    ):
        if not 1 <= port <= 65535:
            failures.append(f"{label} must be between 1 and 65535 (got {port})")
    if config.gcs_udp_port == config.connector_udp_port:
        failures.append("GCS UDP port and connector UDP port must be different")

    if config.topology == "router":
        if config.simulator != "ardupilot":
            failures.append("router topology currently requires the ArduPilot SITL launcher")
        if config.gcs_udp_port != DEFAULT_GCS_UDP_PORT:
            failures.append(
                "router topology uses the checked-in GCS endpoint 14550; "
                "change the router config before using a custom port"
            )
        if config.connector_udp_port != DEFAULT_CONNECTOR_UDP_PORT:
            failures.append(
                "router topology uses the checked-in connector endpoint 14551; "
                "change the router config before using a custom port"
            )
        router_errors = check_mavlink_router.validate(config.router_config)
        failures.extend(f"MAVLink Router: {error}" for error in router_errors)
        if config.router_runtime not in {"auto", "native", "docker"}:
            failures.append(
                f"router runtime must be auto, native, or docker (got {config.router_runtime!r})"
            )
        elif config.router_runtime == "native" and _find_router_command() is None:
            failures.append(
                "mavlink-routerd was not found; install it or set MAVLINK_ROUTERD "
                "before using --topology router"
            )
        elif config.router_runtime == "docker":
            docker_error = _router_docker_prerequisite_error(config)
            if docker_error:
                failures.append(docker_error)
        elif config.router_runtime == "auto" and _select_router_runtime(config) is None:
            failures.append(
                "mavlink-routerd was not found and the Docker router fallback is unavailable; "
                "install mavlink-routerd, set MAVLINK_ROUTERD, or prepare MAVLINK_ROUTER_ROOT"
            )
        if not 1 <= config.router_port <= 65535:
            failures.append(
                f"router UDP input port must be between 1 and 65535 (got {config.router_port})"
            )
        elif not udp_port_is_available("127.0.0.1", config.router_port):
            failures.append(
                f"router UDP input port 127.0.0.1:{config.router_port} is already in use"
            )

    if config.simulator == "px4":
        for label, port in (
            ("GCS UDP port", config.gcs_udp_port),
            ("connector UDP port", config.connector_udp_port),
        ):
            if 1 <= port <= 65535 and not udp_port_is_available("127.0.0.1", port):
                failures.append(f"{label} 127.0.0.1:{port} is already in use")

    if (
        config.gcs == "qgroundcontrol"
        and config.qgroundcontrol_command is None
        and _find_qgroundcontrol_command() is None
    ):
        failures.append("QGroundControl was requested but is not installed or discoverable")
    elif config.gcs == "mission-planner" and _find_mission_planner_command() is None:
        failures.append("Mission Planner was requested but is not installed or discoverable")

    if not config.flight_blender_root.is_dir():
        failures.append(f"Flight Blender checkout not found: {config.flight_blender_root}")
    elif not (config.flight_blender_root / "docker-compose-dev.yml").is_file():
        failures.append(
            f"Flight Blender Compose file not found: {config.flight_blender_root / 'docker-compose-dev.yml'}"
        )

    if config.simulator == "ardupilot":
        if not config.ardupilot_root.is_dir():
            failures.append(f"ArduPilot checkout not found: {config.ardupilot_root}")
        else:
            try:
                find_copter_binary(config.ardupilot_root)
            except FileNotFoundError as exc:
                failures.append(str(exc))
    elif not config.px4_image.strip():
        failures.append("PX4 Docker image must not be empty")
    elif config.gcs_udp_port != DEFAULT_PX4_GCS_PORT:
        failures.append(
            "PX4's stock SITL image requires GCS UDP port "
            f"{DEFAULT_PX4_GCS_PORT}; use the default port or a MAVLink router "
            "when a different host port is required"
        )
    elif config.connector_udp_port != DEFAULT_PX4_CONNECTOR_PORT:
        failures.append(
            "PX4's stock SITL image requires connector UDP port "
            f"{DEFAULT_PX4_CONNECTOR_PORT}; use the default port or a MAVLink router "
            "when a different host port is required"
        )

    docker_ok, docker_detail = _command_available(["docker", "compose", "version"])
    if not docker_ok:
        failures.append(f"Docker Compose is unavailable: {docker_detail or 'command failed'}")

    if _find_geoid_grid() is None:
        failures.append(
            "PROJ EGM96 geoid grid was not found; set UTM_CONNECTOR_ALTITUDE_GEOID_GRID_PATH"
        )

    if port_is_reachable("127.0.0.1", config.connector_port):
        failures.append(f"connector port 127.0.0.1:{config.connector_port} is already in use")
    if port_is_reachable("127.0.0.1", config.provider_port):
        provider_ok, provider_detail = probe_http_endpoint(config.provider_url)
        if provider_ok:
            print(
                f"[info] Flight Blender port 127.0.0.1:{config.provider_port} is already in use; it will be reused"
            )
        else:
            failures.append(
                f"provider port 127.0.0.1:{config.provider_port} is in use by a service that is not ready: {provider_detail}"
            )
    return failures


def _check_run_hint(config: DemoConfig) -> str:
    """Render the matching start command for a successful prerequisite check."""

    command = ["uv", "run", "python", "scripts/openutm_demo.py"]
    if config.simulator != "ardupilot":
        command.extend(["--simulator", config.simulator])
    if config.px4_image != DEFAULT_PX4_IMAGE:
        command.extend(["--px4-image", config.px4_image])
    if config.home != DEFAULT_HOME:
        command.extend(["--home", config.home])
    if config.vehicle_id != DEFAULT_VEHICLE_ID:
        command.extend(["--vehicle-id", config.vehicle_id])
    if config.provider_port != DEFAULT_PROVIDER_PORT:
        command.extend(["--provider-port", str(config.provider_port)])
    if config.connector_port != DEFAULT_CONNECTOR_PORT:
        command.extend(["--connector-port", str(config.connector_port)])
    if config.gcs_udp_port != DEFAULT_GCS_UDP_PORT:
        command.extend(["--gcs-udp-port", str(config.gcs_udp_port)])
    expected_connector_port = (
        DEFAULT_PX4_CONNECTOR_PORT if config.simulator == "px4" else DEFAULT_CONNECTOR_UDP_PORT
    )
    if config.connector_udp_port != expected_connector_port:
        command.extend(["--connector-udp-port", str(config.connector_udp_port)])
    if config.gcs != "auto":
        command.extend(["--gcs", config.gcs])
    if config.qgroundcontrol_command:
        command.extend(["--qgroundcontrol-command", shlex.join(config.qgroundcontrol_command)])
    if config.topology != "split":
        command.extend(["--topology", config.topology])
    if config.router_config != DEFAULT_ROUTER_CONFIG:
        command.extend(["--router-config", str(config.router_config)])
    if config.router_runtime != DEFAULT_ROUTER_RUNTIME:
        command.extend(["--router-runtime", config.router_runtime])
    default_router_source = REPO_ROOT.parent / "mavlink-router"
    if config.router_source_root != default_router_source:
        command.extend(["--router-source-root", str(config.router_source_root)])
    if config.router_image != DEFAULT_ROUTER_IMAGE:
        command.extend(["--router-image", config.router_image])
    if not config.open_browser:
        command.append("--no-browser")
    if config.verify:
        command.append("--verify")
    if config.verify_mission_format != "canonical":
        command.extend(["--verify-mission-format", config.verify_mission_format])
    return shlex.join(command)


@dataclass
class DemoRunner:
    config: DemoConfig
    processes: list[ManagedProcess] = field(default_factory=list)
    gcs_processes: list[ManagedProcess | ManagedApplication] = field(default_factory=list)
    provider_started_by_us: bool = False
    router_container_name: str | None = None

    def start(self) -> None:
        failures = check_prerequisites(self.config)
        if failures:
            raise DemoSetupError("\n".join(failures))

        _prepare_run_dir(self.config.run_dir)
        latitude, longitude, altitude = _parse_demo_home(self.config.home)
        mission_files = write_demo_mission_files(
            self.config.run_dir,
            vehicle_id=self.config.vehicle_id,
            latitude=latitude,
            longitude=longitude,
            altitude_m=altitude,
        )
        if _provider_endpoint_is_ready(self.config):
            print(f"[info] reusing the healthy Flight Blender service at {self.config.provider_url}")
        else:
            if _ensure_provider_env(self.config.flight_blender_root):
                print(f"[ok] prepared {self.config.flight_blender_root / '.env'} from the local template")

            compose_running = _compose_is_running(self.config)
            compose_command = _compose_up_command(self.config, compose_running=compose_running)
            if not compose_running:
                self.provider_started_by_us = True
                if compose_command[-1] == "--build":
                    print("[info] Flight Blender image is missing; building it now")
                else:
                    print(f"[info] reusing local {FLIGHT_BLENDER_IMAGE} image")
            else:
                print("[info] reusing the running Flight Blender Compose stack")
            result = _run_command(compose_command, cwd=self.config.flight_blender_root, capture_output=False)
            if result.returncode != 0:
                raise DemoSetupError("Flight Blender Docker Compose failed to start")
            print("[ok] Flight Blender Compose is running")
        _wait_for_http(self.config.provider_url, self.config.provider_timeout_s)

        # Docker must publish PX4's host-side UDP endpoints before the
        # connector binds them.  The connector can share the published UDP
        # receiver once the container is running, but the reverse order makes
        # Docker Desktop fail with "address already in use".
        if self.config.simulator == "px4":
            _start_sitl(self)
            self._wait_for_px4_container()

        geoid_grid = _find_geoid_grid()
        assert geoid_grid is not None
        connector_env = os.environ.copy()
        connector_env.update(
            {
                "UTM_CONNECTOR_HOST": "127.0.0.1",
                "UTM_CONNECTOR_PORT": str(self.config.connector_port),
                "UTM_CONNECTOR_BACKEND": "flight-blender",
                "UTM_CONNECTOR_FLIGHT_BLENDER_BASE_URL": self.config.provider_url,
                "UTM_CONNECTOR_FLIGHT_BLENDER_BEARER_TOKEN": generate_token(),
                "UTM_CONNECTOR_STATE_DB_PATH": ":memory:",
                "UTM_CONNECTOR_RECORD_PATH": str(self.config.connector_record_path),
                "UTM_CONNECTOR_ALTITUDE_GEOID_GRID_PATH": str(geoid_grid),
                "UTM_CONNECTOR_MAVLINK_CONNECTIONS": (
                    '[{"vehicle_id":"%s","connection_uri":"udpin:127.0.0.1:%s"}]'
                    % (self.config.vehicle_id, self.config.connector_udp_port)
                ),
            }
        )
        connector = _start_new_process(
            "connector",
            [sys.executable, "-m", "utm_connector"],
            cwd=self.config.adapter_root,
            env=connector_env,
            log_path=self.config.run_dir / "connector.log",
        )
        self.processes.append(connector)
        _wait_for_http(self.config.connector_url, self.config.connector_timeout_s, path="/v1/health")
        print(f"[ok] connector is ready at {self.config.connector_url}")

        if self.config.topology == "router":
            _start_router(self)
        if self.config.simulator != "px4":
            _start_sitl(self)
        self._wait_for_vehicle()
        try:
            gcs_stream = verify_mavlink_stream(
                "127.0.0.1",
                self.config.gcs_udp_port,
                timeout_s=self.config.connector_timeout_s,
            )
        except MavlinkStreamVerificationError as exc:
            raise DemoSetupError(f"GCS MAVLink stream is not receiving vehicle telemetry: {exc}") from exc
        print(
            f"[ok] GCS MAVLink stream is receiving vehicle {gcs_stream.system_id} "
            f"on UDP {gcs_stream.port}"
        )
        gcs_label, gcs_process = _launch_gcs(
            self.config.gcs,
            run_dir=self.config.run_dir,
            qgroundcontrol_command=self.config.qgroundcontrol_command,
        )
        if gcs_process is not None:
            self.gcs_processes.append(gcs_process)
        if self.config.verify and gcs_label:
            _wait_for_gcs(
                gcs_label,
                gcs_process,
                timeout_s=min(10.0, self.config.connector_timeout_s),
                log_path=self.config.run_dir
                / ("qgroundcontrol.log" if gcs_label == "QGroundControl" else "mission-planner.log"),
            )
        if self.config.open_browser:
            webbrowser.open(f"{self.config.connector_url}/ui/")
        print("")
        print("UTM demo is ready")
        print(f"  Operator console: {self.config.connector_url}/ui/")
        print(
            f"  Vehicle:          {self.config.vehicle_id} "
            f"({self.config.simulator} / {self.config.topology} MAVLink topology)"
        )
        if self.config.topology == "router":
            router_runtime = _select_router_runtime(self.config) or "unknown"
            print(
                f"  MAVLink Router:   vehicle UDP {self.config.router_port} -> "
                f"GCS {self.config.gcs_udp_port}, connector {self.config.connector_udp_port} "
                f"({router_runtime})"
            )
        else:
            print(
                f"  MAVLink outputs:  GCS UDP {self.config.gcs_udp_port}, "
                f"connector UDP {self.config.connector_udp_port}"
            )
        print("  Workflow:         choose Sample route or open a GCS mission, Validate & save, Submit, Start")
        print("  Mission files:     " + ", ".join(str(path) for path in mission_files.values()))
        if gcs_label:
            print(f"  GCS:              {gcs_label}")
        print("  Stop:             Ctrl+C (cleans up processes and the Docker stack started by this run)")

    def _wait_for_vehicle(self) -> None:
        deadline = time.monotonic() + self.config.connector_timeout_s
        last_detail = "no vehicle yet"
        while time.monotonic() < deadline:
            for managed in self.processes:
                return_code = managed.process.poll()
                if return_code is not None:
                    raise DemoSetupError(
                        f"{managed.name} exited with code {return_code}; "
                        f"see {self.config.run_dir}"
                    )
            try:
                response = httpx.get(f"{self.config.connector_url}/v1/vehicles", timeout=1.5)
                if response.is_success:
                    vehicles = response.json()
                    if any(item.get("vehicle_id") == self.config.vehicle_id for item in vehicles):
                        print(f"[ok] vehicle {self.config.vehicle_id} is online")
                        return
                    last_detail = "connector is ready but SITL has not sent a heartbeat"
            except httpx.HTTPError as exc:
                last_detail = str(exc)
            time.sleep(1.0)
        raise DemoSetupError(last_detail)

    def _wait_for_px4_container(self) -> None:
        deadline = time.monotonic() + self.config.connector_timeout_s
        last_detail = "PX4 container has not been created"
        while time.monotonic() < deadline:
            result = _run_command(["docker", "inspect", self.config.px4_container_name])
            if result.returncode == 0:
                print(f"[ok] PX4 container {self.config.px4_container_name} is running")
                return
            if self.processes and self.processes[-1].process.poll() is not None:
                raise DemoSetupError(
                    f"PX4 SITL exited with code {self.processes[-1].process.returncode}; see {self.config.run_dir}"
                )
            last_detail = (result.stderr or result.stdout or last_detail).strip()
            time.sleep(0.25)
        raise DemoSetupError(f"PX4 container did not become ready: {last_detail}")

    def stop(self) -> None:
        previous_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            for managed in reversed(self.gcs_processes):
                managed.stop()
            self.gcs_processes.clear()
            for managed in reversed(self.processes):
                managed.stop()
            self.processes.clear()
            if self.router_container_name:
                _run_command(
                    ["docker", "rm", "-f", self.router_container_name],
                    capture_output=True,
                )
                self.router_container_name = None
            if self.provider_started_by_us and not self.config.keep_provider:
                result = _run_command(
                    [*_compose_base_command(self.config), "down", "--timeout", "5"],
                    cwd=self.config.flight_blender_root,
                    capture_output=False,
                    start_new_session=os.name != "nt",
                    timeout_s=30,
                )
                if result.returncode == 0:
                    print("[ok] stopped the Flight Blender Compose stack")
                else:
                    print("[warn] Flight Blender Compose cleanup returned a non-zero exit code")
        except subprocess.TimeoutExpired:
            print("[warn] Flight Blender Compose cleanup timed out; inspect Docker manually")
        except KeyboardInterrupt:
            # The SIGINT mask above should make this unreachable, but keep
            # shutdown best-effort if a platform delivers an already-pending
            # interrupt while a child is being reaped.
            print("[warn] Flight Blender cleanup was interrupted; inspect Docker manually")
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)


def _start_sitl(runner: DemoRunner) -> None:
    config = runner.config
    if config.simulator == "px4":
        command = [
            sys.executable,
            str(config.adapter_root / "scripts" / "px4_sitl.py"),
            "--docker-image",
            config.px4_image,
            "--home",
            config.home,
            "--gcs-port",
            str(config.gcs_udp_port),
            "--connector-port",
            str(config.connector_udp_port),
            "--container-name",
            config.px4_container_name,
        ]
        cwd = config.adapter_root
        name = "PX4 SITL"
    else:
        command = [
            sys.executable,
            str(config.adapter_root / "scripts" / "ardupilot_sitl.py"),
            "--ardupilot-root",
            str(config.ardupilot_root),
            "--home",
            config.home,
        ]
        if config.topology == "router":
            command.extend(["--router-port", str(config.router_port)])
        else:
            command.extend(
                [
                    "--gcs-port",
                    str(config.gcs_udp_port),
                    "--connector-port",
                    str(config.connector_udp_port),
                ]
            )
        cwd = config.ardupilot_root
        name = "ArduPilot SITL"
    sitl = _start_new_process(
        name,
        command,
        cwd=cwd,
        env=os.environ.copy(),
        log_path=config.run_dir / "sitl.log",
    )
    runner.processes.append(sitl)


def _start_router(runner: DemoRunner) -> None:
    config = runner.config
    runtime = _select_router_runtime(config)
    if runtime is None:  # pragma: no cover - guarded by preflight
        raise DemoSetupError(
            "no usable MAVLink Router runtime was found; install mavlink-routerd or prepare Docker"
        )
    if runtime == "native":
        command_path = _find_router_command()
        if command_path is None:  # pragma: no cover - guarded by preflight
            raise DemoSetupError("mavlink-routerd was not found")
        command = [command_path, "--conf-file", str(config.router_config)]
        print(f"[ok] MAVLink Router is forwarding {config.router_config} (native)")
    else:
        _ensure_router_image(config)
        runner.router_container_name = config.router_container_name
        router_host_ip = _docker_router_host_ip(config)
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            config.router_container_name,
            "--add-host",
            "host.docker.internal:host-gateway",
            "--publish",
            f"{config.router_port}:{config.router_port}/udp",
            config.router_image,
            "-e",
            f"{router_host_ip}:{config.gcs_udp_port}",
            "-e",
            f"{router_host_ip}:{config.connector_udp_port}",
            "-t",
            "0",
            f"0.0.0.0:{config.router_port}",
        ]
        print(
            f"[ok] MAVLink Router is forwarding the checked-in topology (Docker image {config.router_image})"
        )
    router = _start_new_process(
        "MAVLink Router",
        command,
        cwd=config.adapter_root,
        env=os.environ.copy(),
        log_path=config.run_dir / "mavlink-router.log",
    )
    runner.processes.append(router)


def _ensure_router_image(config: DemoConfig) -> None:
    if _router_image_is_available(config):
        return
    docker_error = _router_docker_prerequisite_error(config)
    if docker_error:
        raise DemoSetupError(docker_error)
    dockerfile = config.router_source_root / "examples" / "Dockerfile.ubuntu"
    print(f"[info] building {config.router_image} from {config.router_source_root}")
    result = _run_command(
        [
            "docker",
            "build",
            "--tag",
            config.router_image,
            "--file",
            str(dockerfile),
            str(config.router_source_root),
        ],
        capture_output=False,
    )
    if result.returncode != 0:
        raise DemoSetupError(f"Docker MAVLink Router image build failed: {config.router_image}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = _config_from_args(args)
    if args.check:
        failures = check_prerequisites(config)
        if failures:
            for failure in failures:
                print(f"[fail] {failure}")
            return 1
        print("[ok] full-stack prerequisites are ready")
        print(f"      run: {_check_run_hint(config)}")
        return 0

    runner = DemoRunner(config)
    try:
        runner.start()
        if config.verify:
            result = verify_running_demo(
                config.connector_url,
                config.vehicle_id,
                timeout_s=config.connector_timeout_s,
                mission_format=config.verify_mission_format,
            )
            print(
                "[ok] full-stack verification passed: "
                f"vehicle={result.vehicle_id} operation={result.operation_id} "
                f"mission_format={result.mission_format} published_samples={result.published_samples} "
                f"elapsed={result.elapsed_s:.1f}s"
            )
            return 0
        while True:
            for managed in runner.processes:
                return_code = managed.process.poll()
                if return_code is not None:
                    raise DemoSetupError(
                        f"{managed.name} exited with code {return_code}; see {config.run_dir}"
                    )
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping UTM demo…")
        return 0
    except DemoVerificationError as exc:
        print(f"[fail] full-stack verification: {exc}")
        return 1
    except DemoSetupError as exc:
        print(f"[fail] {exc}")
        return 1
    finally:
        runner.stop()


if __name__ == "__main__":
    raise SystemExit(main())
