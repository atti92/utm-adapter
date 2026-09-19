from pathlib import Path


ROOT = Path(__file__).parents[1]
QGC_EXAMPLE = ROOT / "examples" / "qgroundcontrol-custom-build"


def test_qgroundcontrol_overlay_is_a_non_commanding_custom_build_layer() -> None:
    qml = (QGC_EXAMPLE / "src" / "FlyViewCustomLayer.qml").read_text()

    assert "GET /v1/health" not in qml  # The path is passed to XMLHttpRequest.
    assert 'requestJson("/v1/health"' in qml
    assert 'requestJson("/v1/vehicles"' in qml
    assert 'Qt.openUrlExternally(root.connectorBaseUrl + "/ui/")' in qml
    assert "QGCButton" in qml
    assert "MAV_CMD" not in qml
    assert "sendMavlink" not in qml
    assert "COMMAND_LONG" not in qml
    assert "vehicleControl" not in qml


def test_qgroundcontrol_overlay_uses_the_official_fly_view_resource_alias() -> None:
    cmake = (QGC_EXAMPLE / "CMakeLists.fragment.cmake").read_text()

    assert "QGroundControl/FlyView/FlyViewCustomLayer.qml" in cmake
    assert "qt_add_resources" in cmake
    assert 'PREFIX "/Custom/qml"' in cmake


def test_qgroundcontrol_overlay_documents_stock_binary_boundary() -> None:
    readme = (QGC_EXAMPLE / "README.md").read_text()

    assert "custom-build integration" in readme
    assert "stock QGroundControl binary" in readme
    assert "does not send" in readme and "MAVLink commands" in readme
