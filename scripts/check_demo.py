"""Run the cross-platform preflight for the operator-facing demo.

The full-stack prerequisites are required for the supervised Flight Blender
demo. Native GCS builds and a MAVLink router are optional: the browser console
and the two-output SITL shortcut work without them, but this command reports
their status so a demo host can be prepared deliberately.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_mavlink_router, check_mission_planner_plugin, check_qgc_overlay, openutm_demo


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--simulator",
        choices=("ardupilot", "px4"),
        default="ardupilot",
        help="full-stack simulator to preflight (default: ardupilot)",
    )
    parser.add_argument(
        "--topology",
        choices=("split", "router"),
        default="split",
        help="MAVLink wiring to preflight (default: split)",
    )
    parser.add_argument(
        "--gcs",
        choices=("auto", "none", "qgroundcontrol", "mission-planner"),
        default="auto",
        help="GCS selection to validate for the supervised launcher",
    )
    parser.add_argument(
        "--flight-blender-root",
        type=Path,
        default=openutm_demo._default_checkout("FLIGHT_BLENDER_ROOT", "flight-blender"),
    )
    parser.add_argument(
        "--ardupilot-root",
        type=Path,
        default=openutm_demo._default_checkout("ARDUPILOT_ROOT", "ardupilot"),
    )
    parser.add_argument(
        "--router-config",
        type=Path,
        default=Path(os.environ.get("MAVLINK_ROUTER_CONFIG", check_mavlink_router.DEFAULT_CONFIG)),
    )
    parser.add_argument(
        "--router-runtime",
        choices=("auto", "native", "docker"),
        default=os.environ.get("MAVLINK_ROUTER_RUNTIME", openutm_demo.DEFAULT_ROUTER_RUNTIME),
        help="router runtime to check (default: auto-select native then Docker)",
    )
    parser.add_argument(
        "--router-source-root",
        type=Path,
        default=openutm_demo._default_checkout("MAVLINK_ROUTER_ROOT", "mavlink-router"),
    )
    parser.add_argument(
        "--router-image",
        default=os.environ.get("MAVLINK_ROUTER_IMAGE", openutm_demo.DEFAULT_ROUTER_IMAGE),
    )
    parser.add_argument(
        "--strict-router",
        action="store_true",
        help="require a usable native or Docker MAVLink Router runtime",
    )
    return parser


def _demo_config(args: argparse.Namespace) -> openutm_demo.DemoConfig:
    connector_udp_port = (
        openutm_demo.DEFAULT_PX4_CONNECTOR_PORT
        if args.simulator == "px4"
        else openutm_demo.DEFAULT_CONNECTOR_UDP_PORT
    )
    return openutm_demo.DemoConfig(
        simulator=args.simulator,
        topology=args.topology,
        gcs=args.gcs,
        flight_blender_root=args.flight_blender_root.expanduser().resolve(),
        ardupilot_root=args.ardupilot_root.expanduser().resolve(),
        connector_udp_port=connector_udp_port,
        router_config=args.router_config.expanduser().resolve(),
        router_runtime=args.router_runtime,
        router_source_root=args.router_source_root.expanduser().resolve(),
        router_image=args.router_image,
    )


def _print_required(config: openutm_demo.DemoConfig) -> bool:
    print("Required full-stack demo checks")
    print("--------------------------------")
    failures = openutm_demo.check_prerequisites(config)
    if failures:
        for failure in failures:
            print(f"[fail] {failure}")
        return False
    print("[ok] supervised demo prerequisites are ready")
    print(f"     start: {openutm_demo._check_run_hint(config)}")
    return True


def _print_optional(args: argparse.Namespace) -> bool:
    print("\nOptional GCS and router checks")
    print("------------------------------")
    optional_ok = True

    router_config = args.router_config.expanduser().resolve()
    router_errors = check_mavlink_router.validate(router_config)
    if router_errors:
        optional_ok = False
        for error in router_errors:
            print(f"[error] MAVLink Router: {error}")
    else:
        print(f"[ok] MAVLink Router topology: {router_config}")
        router_config_for_runtime = openutm_demo.DemoConfig(
            router_config=router_config,
            router_runtime=args.router_runtime,
            router_source_root=args.router_source_root.expanduser().resolve(),
            router_image=args.router_image,
        )
        runtime = openutm_demo._select_router_runtime(router_config_for_runtime)
        router_binary = openutm_demo._find_router_command()
        if runtime == "native" and router_binary:
            print(f"[ok] mavlink-routerd: {router_binary}")
        elif runtime == "docker":
            if openutm_demo._router_image_is_available(router_config_for_runtime):
                print(f"[ok] Docker MAVLink Router image: {args.router_image}")
            else:
                print(
                    "[ok] Docker MAVLink Router fallback: source checkout available "
                    f"at {router_config_for_runtime.router_source_root} (image will be built on first run)"
                )
        elif args.strict_router:
            optional_ok = False
            print(
                "[error] no usable MAVLink Router runtime; install mavlink-routerd or "
                "prepare the Docker fallback"
            )
        else:
            print(
                "[info] MAVLink Router not available; two-output SITL remains available"
            )

    qgc = openutm_demo._find_qgroundcontrol_command()
    if qgc:
        print(f"[ok] QGroundControl: {' '.join(qgc)}")
    else:
        print("[info] QGroundControl not detected; install it for the native GCS view")

    mission_planner = openutm_demo._find_mission_planner_command()
    if mission_planner:
        print(f"[ok] Mission Planner: {' '.join(mission_planner)}")
    else:
        print("[info] Mission Planner not detected; it is normally installed on Windows")

    qgc_source = Path(os.environ.get("QGC_SOURCE_DIR", ROOT.parent / "qgroundcontrol")).expanduser()
    qgc_errors = check_qgc_overlay.validate(qgc_source.resolve(), "v5.1.4") if qgc_source.is_dir() else []
    if qgc_errors:
        print(f"[warn] QGroundControl overlay source: {qgc_errors[0]}")
    elif qgc_source.is_dir():
        print(f"[ok] QGroundControl overlay contract: {qgc_source.resolve()}")
    else:
        print("[info] QGroundControl source checkout not found; native overlay build not checked")

    mission_planner_source = Path(
        os.environ.get("MISSION_PLANNER_SOURCE", ROOT.parent / "MissionPlanner")
    ).expanduser()
    mission_planner_errors = (
        check_mission_planner_plugin.validate(mission_planner_source.resolve(), "1.3.83")
        if mission_planner_source.is_dir()
        else []
    )
    if mission_planner_errors:
        print(f"[warn] Mission Planner plugin contract: {mission_planner_errors[0]}")
    elif mission_planner_source.is_dir():
        print(f"[ok] Mission Planner plugin contract: {mission_planner_source.resolve()}")
    else:
        print("[info] Mission Planner source checkout not found; plugin contract not checked")

    return optional_ok


def _print_setup_guidance(config: openutm_demo.DemoConfig) -> None:
    """Print the shortest setup path for a host that is preparing a demo."""

    setup_command = ["uv", "run", "python", "scripts/setup_demo.py"]
    if config.simulator != "ardupilot":
        setup_command.extend(["--simulator", config.simulator])
    if config.topology != "split":
        setup_command.extend(["--topology", config.topology])
    if config.flight_blender_root != ROOT.parent / "flight-blender":
        setup_command.extend(["--flight-blender-root", str(config.flight_blender_root)])
    if config.simulator == "ardupilot" and config.ardupilot_root != ROOT.parent / "ardupilot":
        setup_command.extend(["--ardupilot-root", str(config.ardupilot_root)])
    if config.topology == "router" and config.router_source_root != ROOT.parent / "mavlink-router":
        setup_command.extend(["--router-source-root", str(config.router_source_root)])

    print("\nSetup guidance")
    print("--------------")
    print("1. Install uv and Docker Desktop (or Docker Engine with Compose).")
    print("2. Use the browser operator console for the UTM workflow; a native GCS is optional.")
    print("   QGroundControl is supported on macOS, Linux, and Windows; Mission Planner is Windows-only.")
    print(f"3. Prepare missing demo dependencies safely: {shlex.join(setup_command)}")
    print("   Add --build-ardupilot for a fresh ArduCopter SITL build, or --simulator px4 for Docker-only PX4.")
    if config.simulator == "ardupilot":
        print(f"4. ArduPilot SITL checkout/build: {config.ardupilot_root}")
    else:
        print("4. PX4 uses the official Docker SITL image; no PX4 or ArduPilot checkout is required.")
    print(f"5. Flight Blender checkout: {config.flight_blender_root}")
    if config.topology == "router":
        print("6. Router topology: install mavlink-routerd or provide the Docker router fallback.")
        print("   The setup helper prepares the fallback source when --topology router is selected.")
        print("7. Run this check again, then start the printed supervised-demo command.")
    else:
        print("6. Run this check again, then start the printed supervised-demo command.")
    print("   The connector remains non-commanding and the GCS remains the vehicle-control application.")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    required_ok = _print_required(_demo_config(args))
    optional_ok = _print_optional(args)
    _print_setup_guidance(_demo_config(args))
    print("\nResult")
    print("------")
    if not required_ok:
        print("[fail] demo host is not ready; fix the required checks above")
        return 1
    if not optional_ok:
        print("[warn] required demo is ready; strict optional integration checks need attention")
        return 1 if args.strict_router else 0
    print("[ok] demo host is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
