from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "examples" / "mission-planner-plugin" / "UtmConnectorPlugin.cs"
INSTALLER = PLUGIN.parent / "Install-UtmConnectorPlugin.ps1"


def test_mission_planner_plugin_is_thin_non_commanding_and_supports_gcs_workflow() -> None:
    source = PLUGIN.read_text()

    assert "class UtmConnectorPlugin : Plugin" in source
    assert 'FullStackConnectorBaseUrl = "http://127.0.0.1:8001"' in source
    assert "ResolveConnectorBaseUrl()" in source
    assert "MissionValidityLeadSeconds = 15" in source
    assert "Host.MainForm.MainMenu.Items" in source
    assert "ToolStripDropDownButton" in source
    assert '"/ui/"' in source
    assert "HttpWebRequest" in source
    assert "Settings.Instance.Save()" in source
    assert "Host.comPort." not in source
    assert "Sync current mission" in source
    assert "Check vehicle mission" in source
    assert 'missionPath + "/refresh"' in source
    assert "vehicle mission received" in source
    assert "Thread.Sleep(500)" in source
    assert "MAVLink.MAV_CMD.LAND" in source
    assert "geographic WAYPOINT, TAKEOFF, and LAND" in source
    assert "IsHomeRow(row, command, home.Lat, home.Lng)" in source
    assert "Mission Planner keeps its home point as row 0" in source
    assert "Submit operation" in source
    assert "START_OPERATION" in source
    assert "Refresh operation status" in source
    assert "/v1/operations/" in source
    assert "telemetry_publication" in source
    assert "conformance" in source
    assert "doCommand" not in source
    assert "sendPacket" not in source
    assert "COMMAND_LONG" not in source


def test_mission_planner_compatibility_check_has_an_explicit_runtime_boundary() -> None:
    script = (PLUGIN.parents[2] / "scripts" / "check_mission_planner_plugin.py").read_text()

    assert "--mission-planner-source" in script
    assert "--expected-version" in script
    assert "1.3.83" in script
    assert "Windows" in script
    assert "COMMAND_LONG" in script
    assert "MAV_CMD.LAND" in script
    assert "main toolbar insertion anchor" in script
    assert "flight planner mission columns" in script
    assert "settings string indexer" in script


def test_mission_planner_installer_is_explicit_and_recoverable() -> None:
    source = INSTALLER.read_text()

    assert "MissionPlannerRoot" in source
    assert "-Force" in source
    assert ".bak" in source
    assert "UtmConnectorPlugin.cs" in source
    assert "Copy-Item" in source


def test_mission_planner_plugin_marshals_async_results_to_the_gcs_ui_thread() -> None:
    source = PLUGIN.read_text()

    assert "Task.Run" in source
    assert "Host.MainForm.BeginInvoke" in source
    assert 'RunRequest("Syncing mission"' in source
