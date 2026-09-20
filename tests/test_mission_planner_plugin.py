from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "examples" / "mission-planner-plugin" / "UtmConnectorPlugin.cs"


def test_mission_planner_plugin_is_thin_non_commanding_and_supports_gcs_workflow() -> None:
    source = PLUGIN.read_text()

    assert "class UtmConnectorPlugin : Plugin" in source
    assert 'FullStackConnectorBaseUrl = "http://127.0.0.1:8001"' in source
    assert "ResolveConnectorBaseUrl()" in source
    assert "MissionValidityLeadSeconds = 15" in source
    assert "Host.FDMenuMap.Items.Add(connectorMenu)" in source
    assert '"/ui/"' in source
    assert "HttpWebRequest" in source
    assert "Host.comPort." not in source
    assert "Sync current mission" in source
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
