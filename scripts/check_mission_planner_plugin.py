"""Validate the thin Mission Planner plugin against an upstream source tree.

Mission Planner is a Windows/.NET Framework application. This check verifies
the script-plugin API surface and the non-commanding boundary on any host;
the final C# compilation and menu test still require Windows and Mission
Planner itself.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "examples" / "mission-planner-plugin" / "UtmConnectorPlugin.cs"


def _git_revision(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _project_version(project: Path) -> str | None:
    match = re.search(r"<Version>([^<]+)</Version>", project.read_text())
    return match.group(1) if match else None


def validate(source_root: Path, expected_version: str) -> list[str]:
    required = {
        "Mission Planner plugin API": source_root / "Plugin" / "Plugin.cs",
        "Mission Planner main form": source_root / "MainV2.Designer.cs",
        "Mission Planner main form implementation": source_root / "MainV2.cs",
        "Mission Planner flight planner": source_root / "GCSViews" / "FlightPlanner.cs",
        "Mission Planner flight planner designer": source_root / "GCSViews" / "FlightPlanner.Designer.cs",
        "Mission Planner current state": source_root / "ExtLibs" / "ArduPilot" / "CurrentState.cs",
        "Mission Planner settings": source_root / "ExtLibs" / "Utilities" / "Settings.cs",
        "Mission Planner MAVLink enums": source_root / "ExtLibs" / "Mavlink" / "Mavlink.cs",
        "Mission Planner project": source_root / "MissionPlanner.csproj",
        "plugin source": PLUGIN,
        "PowerShell installer": PLUGIN.parent / "Install-UtmConnectorPlugin.ps1",
    }
    errors = [f"{label} missing: {path}" for label, path in required.items() if not path.is_file()]
    if errors:
        return errors

    api = required["Mission Planner plugin API"].read_text(encoding="utf-8-sig")
    main_form = required["Mission Planner main form"].read_text(encoding="utf-8-sig")
    main_form_implementation = required["Mission Planner main form implementation"].read_text(encoding="utf-8-sig")
    flight_planner = required["Mission Planner flight planner"].read_text(encoding="utf-8-sig")
    flight_planner_designer = required["Mission Planner flight planner designer"].read_text(encoding="utf-8-sig")
    current_state = required["Mission Planner current state"].read_text(encoding="utf-8-sig")
    settings = required["Mission Planner settings"].read_text(encoding="utf-8-sig")
    mavlink = required["Mission Planner MAVLink enums"].read_text(encoding="utf-8-sig")
    project = required["Mission Planner project"]
    plugin = PLUGIN.read_text(encoding="utf-8-sig")
    installer = required["PowerShell installer"].read_text(encoding="utf-8-sig")
    source_csharp_files = source_root.rglob("*.cs")
    source_text = "\n".join(
        path.read_text(encoding="utf-8-sig", errors="ignore") for path in source_csharp_files
    )
    has_settings_getter = any(
        "GetString(" in path.read_text(encoding="utf-8-sig", errors="ignore")
        for path in source_root.rglob("*.cs")
    )
    expectations = (
        ("plugin base class", "public abstract class Plugin" in api),
        ("plugin initialization hook", "public abstract bool Init()" in api),
        ("plugin load hook", "public abstract bool Loaded()" in api),
        ("plugin unload hook", "public abstract bool Exit()" in api),
        (
            "main toolbar surface",
            "MenuStrip MainMenu"
            in main_form,
        ),
        ("main toolbar insertion anchor", 'this.MenuHelp.Name = "MenuHelp"' in main_form),
        ("main form flight planner surface", "public GCSViews.FlightPlanner FlightPlanner" in main_form_implementation),
        ("flight planner mission grid", "this.Commands.Name = \"Commands\"" in flight_planner_designer),
        (
            "flight planner mission columns",
            all(
                f'this.{name}.Name = "{name}"' in flight_planner_designer
                for name in ("Command", "Frame", "Param1", "Param2", "Param3", "Param4", "Lat", "Lon", "Alt")
            ),
        ),
        ("flight planner refresh method", "public void BUT_read_Click" in flight_planner),
        ("current home location surface", "public PointLatLngAlt HomeLocation" in current_state),
        ("planned home location surface", "public PointLatLngAlt PlannedHomeLocation" in current_state),
        ("settings string getter", "public string GetString(string key" in settings and has_settings_getter),
        ("settings string indexer", "public string this[string key]" in settings and "set" in settings),
        ("settings persistence method", "public void Save()" in settings),
        ("MAVLink geographic frame enum", "GLOBAL_RELATIVE_ALT" in mavlink),
        ("MAVLink geographic command enum", all(f"{name}=" in mavlink for name in ("WAYPOINT", "TAKEOFF", "LAND"))),
        ("connector plugin derives from Plugin", "class UtmConnectorPlugin : Plugin" in plugin),
        ("installer accepts a Mission Planner root", "MissionPlannerRoot" in installer),
        ("installer protects existing plugins", "-Force" in installer and ".bak" in installer),
        ("installer copies the C# plugin", "Copy-Item" in installer and "UtmConnectorPlugin.cs" in installer),
        ("connector plugin uses the main toolbar", "Host.MainForm.MainMenu.Items" in plugin and "ToolStripDropDownButton" in plugin),
        ("connector settings persist", "Settings.Instance.Save()" in plugin),
        ("connector plugin remains non-commanding", "Host.comPort." not in plugin),
        ("connector plugin has no MAVLink command path", "COMMAND_LONG" not in plugin and "sendPacket" not in plugin),
        (
            "connector plugin uses geographic mission commands",
            all(f"MAVLink.MAV_CMD.{name}" in plugin for name in ("WAYPOINT", "LAND", "TAKEOFF")),
        ),
        (
            "Mission Planner exposes the LAND mission enum",
            "MAV_CMD.LAND" in source_text,
        ),
    )
    for label, passed in expectations:
        if not passed:
            errors.append(f"{label} check failed")

    version = _project_version(project)
    if expected_version and version != expected_version:
        errors.append(
            f"Mission Planner source reports version {version or 'unknown'}; expected {expected_version}"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mission-planner-source",
        type=Path,
        default=Path(os.environ.get("MISSION_PLANNER_SOURCE", ROOT.parent / "MissionPlanner")),
        help="Mission Planner checkout (default: MISSION_PLANNER_SOURCE or ../MissionPlanner)",
    )
    parser.add_argument(
        "--expected-version",
        default="1.3.83",
        help="Mission Planner source version to validate (default: 1.3.83)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when the Mission Planner source checkout is unavailable",
    )
    args = parser.parse_args()
    source_root = args.mission_planner_source.expanduser().resolve()

    if not source_root.is_dir():
        message = f"Mission Planner source not found at {source_root}"
        if args.strict:
            print(f"[error] {message}")
            return 1
        print(f"[skip] {message}; validate on Windows or provide a source checkout")
        return 0

    errors = validate(source_root, args.expected_version)
    if errors:
        for error in errors:
            print(f"[error] {error}")
        return 1

    print(f"[ok] Mission Planner {args.expected_version} plugin contract is valid")
    revision = _git_revision(source_root)
    if revision:
        print(f"[ok] source revision: {revision}")
    print("[info] final C# compilation and menu verification require Windows with Mission Planner installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
