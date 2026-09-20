"""Run the cross-platform preflight for the operator-facing demo.

The full-stack prerequisites are required for the supervised Flight Blender
demo. Native GCS builds and a MAVLink router are optional: the browser console
and the two-output SITL shortcut work without them, but this command reports
their status so a demo host can be prepared deliberately.
"""

from __future__ import annotations

import argparse
import os
import shutil
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
        "--strict-router",
        action="store_true",
        help="make the optional router binary check required",
    )
    return parser


def _demo_config(args: argparse.Namespace) -> openutm_demo.DemoConfig:
    return openutm_demo.DemoConfig(
        simulator=args.simulator,
        gcs=args.gcs,
        flight_blender_root=args.flight_blender_root.expanduser().resolve(),
        ardupilot_root=args.ardupilot_root.expanduser().resolve(),
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

    router_errors = check_mavlink_router.validate(args.router_config.expanduser().resolve())
    if router_errors:
        optional_ok = False
        for error in router_errors:
            print(f"[error] MAVLink Router: {error}")
    else:
        print(f"[ok] MAVLink Router topology: {args.router_config.expanduser().resolve()}")
        router_binary = shutil.which("mavlink-routerd")
        if router_binary:
            print(f"[ok] mavlink-routerd: {router_binary}")
        elif args.strict_router:
            optional_ok = False
            print("[error] mavlink-routerd is not installed or not on PATH")
        else:
            print("[info] mavlink-routerd not installed; two-output SITL remains available")

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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    required_ok = _print_required(_demo_config(args))
    optional_ok = _print_optional(args)
    print("\nResult")
    print("------")
    if not required_ok:
        print("[fail] demo host is not ready; fix the required checks above")
        return 1
    if not optional_ok:
        print("[warn] required demo is ready; strict optional integration checks need attention")
        return 0
    print("[ok] demo host is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
