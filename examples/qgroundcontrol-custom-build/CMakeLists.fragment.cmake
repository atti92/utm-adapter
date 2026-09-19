# Merge this fragment into a QGroundControl custom-build CMakeLists.txt.
# The alias is the important part: it replaces the additive Fly View layer
# resource used by QGroundControl's custom-example build.

set(UTM_CONNECTOR_QML_OVERRIDE
    "${CMAKE_CURRENT_SOURCE_DIR}/src/FlyViewCustomLayer.qml"
)

set_source_files_properties(
    "${UTM_CONNECTOR_QML_OVERRIDE}"
    PROPERTIES QT_RESOURCE_ALIAS "QGroundControl/FlyView/FlyViewCustomLayer.qml"
)

qt_add_resources(${CMAKE_PROJECT_NAME} utm_connector_qml_overrides
    PREFIX "/Custom/qml"
    FILES ${UTM_CONNECTOR_QML_OVERRIDE}
)
