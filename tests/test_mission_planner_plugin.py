from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "examples" / "mission-planner-plugin" / "UtmConnectorPlugin.cs"


def test_mission_planner_plugin_is_thin_non_commanding_and_uses_connector_console() -> None:
    source = PLUGIN.read_text()

    assert "class UtmConnectorPlugin : Plugin" in source
    assert "Host.FDMenuMap.Items.Add(connectorMenu)" in source
    assert '"/ui/"' in source
    assert "HttpWebRequest" in source
    assert "Host.comPort." not in source
    assert "MAV_CMD" not in source
    assert "COMMAND_LONG" not in source
