# Merge this fragment into the QGroundControl custom-example CMakeLists.txt.
# QGC adds QGC_RESOURCES to the executable after the custom directory is
# configured. Registering a resource directly on ${CMAKE_PROJECT_NAME} here is
# too early and makes the overlay silently disappear on QGC 5.1.x.

set(UTM_CONNECTOR_CUSTOM_QRC
    "${CMAKE_CURRENT_SOURCE_DIR}/utm_connector.qrc"
)

if(NOT EXISTS "${UTM_CONNECTOR_CUSTOM_QRC}")
    message(FATAL_ERROR
        "UTM connector QGC overlay resource file is missing: ${UTM_CONNECTOR_CUSTOM_QRC}"
    )
endif()

list(FIND CUSTOM_RESOURCES "${UTM_CONNECTOR_CUSTOM_QRC}" _utm_connector_qrc_index)
if(_utm_connector_qrc_index EQUAL -1)
    list(APPEND CUSTOM_RESOURCES "${UTM_CONNECTOR_CUSTOM_QRC}")
endif()

set(QGC_RESOURCES
    ${QGC_RESOURCES}
    ${CUSTOM_RESOURCES}
    CACHE STRING "Paths to .qrc Resources" FORCE
)
