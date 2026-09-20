"""Start a complete local Flight Blender + SITL + connector demo.

The launcher owns only the processes it starts. It is intentionally a small
Python supervisor instead of a shell script so the same workflow works from
macOS, Linux, WSL, and Windows PowerShell. The normal operator interaction
remains in the browser console and the selected GCS; the terminal is only used
to show startup logs and to stop the demo with Ctrl+C.
"""

from __future__ import annotations

import argparse
import os
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
from scripts.generate_flight_blender_dev_token import generate_token
from utm_connector.diagnostics import port_is_reachable, probe_http_endpoint


DEFAULT_VEHICLE_ID = "sitl-1"
DEFAULT_PROVIDER_PORT = 8000
DEFAULT_CONNECTOR_PORT = 8001
DEFAULT_GCS_UDP_PORT = 14550
DEFAULT_CONNECTOR_UDP_PORT = 14551
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
    home: str = DEFAULT_HOME
    vehicle_id: str = DEFAULT_VEHICLE_ID
    provider_port: int = DEFAULT_PROVIDER_PORT
    connector_port: int = DEFAULT_CONNECTOR_PORT
    gcs_udp_port: int = DEFAULT_GCS_UDP_PORT
    connector_udp_port: int = DEFAULT_CONNECTOR_UDP_PORT
    provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S
    connector_timeout_s: float = DEFAULT_CONNECTOR_TIMEOUT_S
    gcs: str = "auto"
    open_browser: bool = True
    keep_provider: bool = False

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
    log_file = log_path.open("ab")
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


def _find_qgroundcontrol_command() -> list[str] | None:
    if sys.platform == "darwin":
        for app_root in (Path("/Applications"), Path.home() / "Applications"):
            executable = app_root / "QGroundControl.app" / "Contents" / "MacOS" / "QGroundControl"
            if executable.is_file() and os.access(executable, os.X_OK):
                return [str(executable)]
        available, _detail = _command_available(["open", "-Ra", "QGroundControl"])
        return ["open", "-a", "QGroundControl"] if available else None
    executable = shutil.which("QGroundControl.exe" if os.name == "nt" else "qgroundcontrol")
    return [executable] if executable else None


def _find_mission_planner_command() -> list[str] | None:
    if os.name != "nt":
        return None
    executable = shutil.which("MissionPlanner.exe")
    return [executable] if executable else None


def _launch_gcs(
    selection: str,
    *,
    run_dir: Path | None = None,
) -> tuple[str | None, ManagedProcess | None]:
    if selection == "none":
        return None, None
    if selection == "mission-planner":
        command = _find_mission_planner_command()
        label = "Mission Planner"
    else:
        command = _find_qgroundcontrol_command()
        label = "QGroundControl"
    if command is None:
        if selection == "auto":
            print("[info] no supported GCS was found; open QGroundControl or Mission Planner manually")
            return None, None
        raise DemoSetupError(f"{label} was requested but was not found on this host")

    managed: ManagedProcess | None = None
    app_launcher = sys.platform == "darwin" and command[:1] == ["open"]
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
            print("[info] macOS app launcher used; the app-managed GCS process is not owned by this run")
    print(f"[ok] launched {label}")
    return label, managed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start Flight Blender, ArduPilot SITL, the UTM connector, and the operator console"
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
        default=DEFAULT_CONNECTOR_UDP_PORT,
        help="SITL UDP input consumed by the connector (default: 14551)",
    )
    parser.add_argument("--provider-timeout", type=float, default=DEFAULT_PROVIDER_TIMEOUT_S)
    parser.add_argument("--connector-timeout", type=float, default=DEFAULT_CONNECTOR_TIMEOUT_S)
    parser.add_argument(
        "--gcs",
        choices=("auto", "none", "qgroundcontrol", "mission-planner"),
        default="auto",
        help="launch a GCS after the vehicle is online (default: auto-detect)",
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open the operator console")
    parser.add_argument(
        "--keep-provider",
        action="store_true",
        help="leave the Flight Blender Compose stack running after Ctrl+C",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only validate prerequisites; do not start Docker, SITL, or the connector",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> DemoConfig:
    return DemoConfig(
        adapter_root=REPO_ROOT,
        flight_blender_root=args.flight_blender_root.expanduser().resolve(),
        ardupilot_root=args.ardupilot_root.expanduser().resolve(),
        home=args.home,
        vehicle_id=args.vehicle_id,
        provider_port=args.provider_port,
        connector_port=args.connector_port,
        gcs_udp_port=args.gcs_udp_port,
        connector_udp_port=args.connector_udp_port,
        provider_timeout_s=args.provider_timeout,
        connector_timeout_s=args.connector_timeout,
        gcs=args.gcs,
        open_browser=not args.no_browser,
        keep_provider=args.keep_provider,
    )


def check_prerequisites(config: DemoConfig) -> list[str]:
    """Return human-readable prerequisite failures without starting anything."""

    failures: list[str] = []
    for label, port in (
        ("GCS UDP port", config.gcs_udp_port),
        ("connector UDP port", config.connector_udp_port),
    ):
        if not 1 <= port <= 65535:
            failures.append(f"{label} must be between 1 and 65535 (got {port})")
    if config.gcs_udp_port == config.connector_udp_port:
        failures.append("GCS UDP port and connector UDP port must be different")

    if config.gcs == "qgroundcontrol" and _find_qgroundcontrol_command() is None:
        failures.append("QGroundControl was requested but is not installed or discoverable")
    elif config.gcs == "mission-planner" and _find_mission_planner_command() is None:
        failures.append("Mission Planner was requested but is not installed or discoverable")

    if not config.flight_blender_root.is_dir():
        failures.append(f"Flight Blender checkout not found: {config.flight_blender_root}")
    elif not (config.flight_blender_root / "docker-compose-dev.yml").is_file():
        failures.append(
            f"Flight Blender Compose file not found: {config.flight_blender_root / 'docker-compose-dev.yml'}"
        )

    if not config.ardupilot_root.is_dir():
        failures.append(f"ArduPilot checkout not found: {config.ardupilot_root}")
    else:
        try:
            find_copter_binary(config.ardupilot_root)
        except FileNotFoundError as exc:
            failures.append(str(exc))

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


@dataclass
class DemoRunner:
    config: DemoConfig
    processes: list[ManagedProcess] = field(default_factory=list)
    gcs_processes: list[ManagedProcess] = field(default_factory=list)
    provider_started_by_us: bool = False

    def start(self) -> None:
        failures = check_prerequisites(self.config)
        if failures:
            raise DemoSetupError("\n".join(failures))

        self.config.run_dir.mkdir(parents=True, exist_ok=True)
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

        _start_sitl(self)
        self._wait_for_vehicle()
        gcs_label, gcs_process = _launch_gcs(self.config.gcs, run_dir=self.config.run_dir)
        if gcs_process is not None:
            self.gcs_processes.append(gcs_process)
        if self.config.open_browser:
            webbrowser.open(f"{self.config.connector_url}/ui/")
        print("")
        print("UTM demo is ready")
        print(f"  Operator console: {self.config.connector_url}/ui/")
        print(
            f"  Vehicle:          {self.config.vehicle_id} "
            f"(GCS UDP {self.config.gcs_udp_port}, connector UDP {self.config.connector_udp_port})"
        )
        print("  Workflow:         choose Sample route or open a GCS mission, Validate & save, Submit, Start")
        if gcs_label:
            print(f"  GCS:              {gcs_label}")
        print("  Stop:             Ctrl+C (cleans up processes and the Docker stack started by this run)")

    def _wait_for_vehicle(self) -> None:
        deadline = time.monotonic() + self.config.connector_timeout_s
        last_detail = "no vehicle yet"
        while time.monotonic() < deadline:
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
    sitl = _start_new_process(
        "ArduPilot SITL",
        [
            sys.executable,
            str(config.adapter_root / "scripts" / "ardupilot_sitl.py"),
            "--ardupilot-root",
            str(config.ardupilot_root),
            "--home",
            config.home,
            "--gcs-port",
            str(config.gcs_udp_port),
            "--connector-port",
            str(config.connector_udp_port),
        ],
        cwd=config.ardupilot_root,
        env=os.environ.copy(),
        log_path=config.run_dir / "sitl.log",
    )
    runner.processes.append(sitl)


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
        print("      run: uv run python scripts/openutm_demo.py")
        return 0

    runner = DemoRunner(config)
    try:
        runner.start()
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
    except DemoSetupError as exc:
        print(f"[fail] {exc}")
        return 1
    finally:
        runner.stop()


if __name__ == "__main__":
    raise SystemExit(main())
