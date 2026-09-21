from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
QGC_EXAMPLE = ROOT / "examples" / "qgroundcontrol-custom-build"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_qgroundcontrol_overlay_submits_utm_actions_without_commanding_the_vehicle() -> None:
    qml = (QGC_EXAMPLE / "src" / "FlyViewCustomLayer.qml").read_text()

    assert "GET /v1/health" not in qml  # The path is passed to XMLHttpRequest.
    assert 'requestJson("/v1/health"' in qml
    assert 'requestJson("/v1/vehicles"' in qml
    assert '"/v1/vehicles/" + encodeURIComponent(vehicle.vehicle_id) + "/status"' in qml
    assert 'property string operationLabel: "No operation"' in qml
    assert 'property string missionLabel: "Mission not checked"' in qml
    assert 'property var _activeVehicle: QGroundControl.multiVehicleManager.activeVehicle' in qml
    assert "function connectorVehicleFor(vehicles)" in qml
    assert "mavlink_system_id" in qml
    assert "No connector match for active vehicle" in qml
    assert 'missionLabel = "Mission: matches"' in qml
    assert 'drift.classification || "drift"' in qml
    assert 'property string fallbackConnectorBaseUrl: "http://127.0.0.1:8001"' in qml
    assert "resolvedConnectorBaseUrl" in qml
    assert "root.fallbackConnectorBaseUrl" in qml
    assert 'state.telemetry_publication' in qml
    assert 'Qt.openUrlExternally(root.resolvedConnectorBaseUrl + "/ui/")' in qml
    assert "submitCurrentPlan" in qml
    assert "sendOperationIntent" in qml
    assert "QGCButton" in qml
    assert "MAV_CMD" not in qml
    assert "sendMavlink" not in qml
    assert "COMMAND_LONG" not in qml
    assert "vehicleControl" not in qml

    bridge_header = (QGC_EXAMPLE / "src" / "UtmConnectorBridge.h").read_text()
    bridge_source = (QGC_EXAMPLE / "src" / "UtmConnectorBridge.cc").read_text()
    assert "saveToJson" in bridge_source
    assert "QNetworkAccessManager" in bridge_source
    assert "sendMavlink" not in bridge_source
    assert "COMMAND_LONG" not in bridge_source
    assert "sendMavlink" not in bridge_header


def test_qgroundcontrol_overlay_uses_the_official_fly_view_resource_alias() -> None:
    cmake = (QGC_EXAMPLE / "CMakeLists.fragment.cmake").read_text()
    qrc = (QGC_EXAMPLE / "utm_connector.qrc").read_text()

    assert "CUSTOM_RESOURCES" in cmake
    assert 'prefix="/Custom/qml"' in qrc
    assert 'alias="QGroundControl/FlyView/FlyViewCustomLayer.qml"' in qrc


def test_qgroundcontrol_overlay_check_script_catches_native_build_drift() -> None:
    script = (ROOT / "scripts" / "check_qgc_overlay.py").read_text()

    assert "addUrlInterceptor" in script
    assert "CUSTOM_RESOURCES" in script
    assert "--strict" in script
    assert "v5.1.4" in script


def test_qgroundcontrol_overlay_documents_stock_binary_boundary() -> None:
    readme = (QGC_EXAMPLE / "README.md").read_text()

    assert "custom-build integration" in readme
    assert "stock QGroundControl binary" in readme
    assert "does not send" in readme and "MAVLink commands" in readme


def test_qgroundcontrol_stager_preserves_upstream_and_replaces_only_fly_view_layer(tmp_path: Path) -> None:
    from scripts.stage_qgc_custom_build import stage_custom_build

    qgc_source = tmp_path / "qgroundcontrol"
    upstream_layer = qgc_source / "custom-example" / "src" / "FlyViewCustomLayer.qml"
    upstream_layer.parent.mkdir(parents=True)
    upstream_layer.write_text("// upstream sample\n", encoding="utf-8")
    (qgc_source / "custom-example" / "CMakeLists.txt").write_text(
        "set(CUSTOM_SOURCES\n"
        "    ${CMAKE_CURRENT_SOURCE_DIR}/src/MissionManager/PerimeterScanPlanCreator.h\n"
        ")\n",
        encoding="utf-8",
    )
    (qgc_source / "custom-example" / "src" / "CustomPlugin.h").write_text(
        '#include "QGCCorePlugin.h"\n'
        "class CustomPlugin : public QGCCorePlugin\n"
        "{\n    Q_OBJECT\n"
        "public:\n    static QGCCorePlugin *instance();\n"
        "private:\n    CustomOptions *_options = nullptr;\n};\n",
        encoding="utf-8",
    )
    (qgc_source / "custom-example" / "src" / "CustomPlugin.cc").write_text(
        '#include "CustomPlugin.h"\n'
        "CustomPlugin::CustomPlugin(QObject *parent)\n"
        "    : QGCCorePlugin(parent)\n"
        "    , _options(new CustomOptions(this, this))\n"
        "{}\n",
        encoding="utf-8",
    )
    (qgc_source / "custom-example" / "custom.qrc").write_text(
        "<qresource prefix=\"/Custom/qml\" />\n", encoding="utf-8"
    )
    (qgc_source / "custom-example" / "cmake").mkdir()
    (qgc_source / "custom-example" / "cmake" / "CustomOverrides.cmake").write_text(
        'set(QGC_DISABLE_APM_PLUGIN_FACTORY ON CACHE BOOL "Disable APM Plugin Factory" FORCE)\n',
        encoding="utf-8",
    )
    output = qgc_source / "custom-utm-connector"

    staged = stage_custom_build(qgc_source, output)

    assert staged == output.resolve()
    assert staged.joinpath("custom.qrc").is_file()
    assert staged.joinpath(".utm-connector-overlay.json").is_file()
    assert staged.joinpath("src", "UtmConnectorBridge.h").is_file()
    assert staged.joinpath("src", "UtmConnectorBridge.cc").is_file()
    staged_cmake = staged.joinpath("CMakeLists.txt").read_text()
    assert "src/UtmConnectorBridge.cc" in staged_cmake
    assert "src/UtmConnectorBridge.h" in staged_cmake
    staged_plugin_header = staged.joinpath("src", "CustomPlugin.h").read_text()
    assert 'Q_PROPERTY(UtmConnectorBridge* utmConnector READ utmConnector CONSTANT)' in staged_plugin_header
    assert 'UtmConnectorBridge *utmConnector() const' in staged_plugin_header
    assert '"UtmConnectorBridge.h"' in staged_plugin_header
    assert 'UtmConnectorBridge *_utmConnector = nullptr;' in staged_plugin_header
    assert 'new UtmConnectorBridge(this)' in staged.joinpath("src", "CustomPlugin.cc").read_text()
    assert 'QGC_DISABLE_APM_PLUGIN_FACTORY OFF' in staged.joinpath(
        "cmake", "CustomOverrides.cmake"
    ).read_text()
    assert staged.joinpath("src", "FlyViewCustomLayer.qml").read_text() == (
        QGC_EXAMPLE / "src" / "FlyViewCustomLayer.qml"
    ).read_text()
    assert upstream_layer.read_text() == "// upstream sample\n"


def test_qgroundcontrol_stager_refuses_unmarked_replacement(tmp_path: Path) -> None:
    from scripts.stage_qgc_custom_build import StageError, stage_custom_build

    qgc_source = tmp_path / "qgroundcontrol"
    upstream_layer = qgc_source / "custom-example" / "src" / "FlyViewCustomLayer.qml"
    upstream_layer.parent.mkdir(parents=True)
    upstream_layer.write_text("// upstream sample\n", encoding="utf-8")
    (qgc_source / "custom-example" / "cmake").mkdir()
    (qgc_source / "custom-example" / "cmake" / "CustomOverrides.cmake").write_text(
        'set(QGC_DISABLE_APM_PLUGIN_FACTORY ON CACHE BOOL "Disable APM Plugin Factory" FORCE)\n',
        encoding="utf-8",
    )
    output = qgc_source / "custom-utm-connector"
    output.mkdir(parents=True)

    with pytest.raises(StageError, match="unmarked"):
        stage_custom_build(qgc_source, output, force=True)


def test_qgroundcontrol_stager_backs_up_its_previous_generated_output(tmp_path: Path) -> None:
    from scripts.stage_qgc_custom_build import stage_custom_build

    qgc_source = tmp_path / "qgroundcontrol"
    upstream_layer = qgc_source / "custom-example" / "src" / "FlyViewCustomLayer.qml"
    upstream_layer.parent.mkdir(parents=True)
    upstream_layer.write_text("// upstream sample\n", encoding="utf-8")
    (qgc_source / "custom-example" / "cmake").mkdir()
    (qgc_source / "custom-example" / "cmake" / "CustomOverrides.cmake").write_text(
        'set(QGC_DISABLE_APM_PLUGIN_FACTORY ON CACHE BOOL "Disable APM Plugin Factory" FORCE)\n',
        encoding="utf-8",
    )
    output = qgc_source / "custom-utm-connector"

    stage_custom_build(qgc_source, output)
    stage_custom_build(qgc_source, output, force=True)

    backups = list(qgc_source.glob("custom-utm-connector.backup-*"))
    assert len(backups) == 1
    assert backups[0].joinpath(".utm-connector-overlay.json").is_file()
    assert output.joinpath(".utm-connector-overlay.json").is_file()


def test_qgroundcontrol_stager_has_a_safe_cli_contract() -> None:
    script = (ROOT / "scripts" / "stage_qgc_custom_build.py").read_text()

    assert "--qgc-source" in script
    assert "--output" in script
    assert "--force" in script
    assert "shutil.move" in script
    assert ".utm-connector-overlay.json" in script
    assert "native_utm_actions" in script
