// UTM connector Fly View overlay for a QGroundControl custom build.
// This layer is deliberately non-commanding: it only reads connector status.

import QtQuick
import QtQuick.Controls
import QGroundControl
import QGroundControl.Controls
import QGroundControl.FlyView
import QGroundControl.FlightMap

Item {
    id: root

    property var parentToolInsets
    property var mapControl
    property var totalToolInsets: toolInsets
    property string connectorBaseUrl: "http://127.0.0.1:8000"
    property string fallbackConnectorBaseUrl: "http://127.0.0.1:8001"
    property string resolvedConnectorBaseUrl: connectorBaseUrl
    property bool connectorOnline: false
    property string connectorLabel: "UTM offline"
    property string vehicleLabel: "No vehicle"
    property string missionLabel: "Mission not checked"
    property string operationLabel: "No operation"
    property var _activeVehicle: QGroundControl.multiVehicleManager.activeVehicle

    function setOffline(label) {
        connectorOnline = false
        connectorLabel = label || "UTM offline"
        vehicleLabel = "No vehicle"
        missionLabel = "Mission not checked"
        operationLabel = "No operation"
    }

    function requestJson(path, callback, baseUrl) {
        var endpoint = baseUrl || root.connectorBaseUrl
        var request = new XMLHttpRequest()
        request.open("GET", endpoint + path)
        request.onreadystatechange = function() {
            if (request.readyState !== 4) {
                return
            }
            if (request.status < 200 || request.status >= 300) {
                if (endpoint === root.connectorBaseUrl
                        && root.connectorBaseUrl === "http://127.0.0.1:8000"
                        && root.fallbackConnectorBaseUrl !== endpoint) {
                    root.requestJson(path, callback, root.fallbackConnectorBaseUrl)
                    return
                }
                setOffline("UTM unavailable")
                return
            }
            try {
                root.resolvedConnectorBaseUrl = endpoint
                callback(JSON.parse(request.responseText), endpoint)
            } catch (error) {
                setOffline("UTM response error")
            }
        }
        request.onerror = function() {
            if (endpoint === root.connectorBaseUrl
                    && root.connectorBaseUrl === "http://127.0.0.1:8000"
                    && root.fallbackConnectorBaseUrl !== endpoint) {
                root.requestJson(path, callback, root.fallbackConnectorBaseUrl)
                return
            }
            setOffline("UTM unavailable")
        }
        request.send()
    }

    function connectorVehicleFor(vehicles) {
        if (!vehicles || vehicles.length === 0) {
            return null
        }
        if (root._activeVehicle) {
            var activeSystemId = Number(root._activeVehicle.id)
            for (var index = 0; index < vehicles.length; index++) {
                if (Number(vehicles[index].mavlink_system_id) === activeSystemId) {
                    return vehicles[index]
                }
            }
            return null
        }
        return vehicles.length === 1 ? vehicles[0] : null
    }

    function refreshStatus() {
        requestJson("/v1/health", function(health, endpoint) {
            connectorOnline = health.status === "ok"
            connectorLabel = connectorOnline
                    ? "UTM ready"
                    : (health.backend_error ? "Provider degraded" : "UTM degraded")
            requestJson("/v1/vehicles", function(vehicles, endpoint) {
                if (vehicles.length === 0) {
                    vehicleLabel = "No vehicle telemetry"
                    operationLabel = "No operation"
                    return
                }
                var vehicle = root.connectorVehicleFor(vehicles)
                if (!vehicle) {
                    vehicleLabel = root._activeVehicle ? "No connector match for active vehicle" : "Select an active vehicle"
                    missionLabel = "Mission not checked"
                    operationLabel = "No operation"
                    return
                }
                vehicleLabel = vehicle.vehicle_id + " · " + (vehicle.quality || "unknown")
                requestJson("/v1/vehicles/" + encodeURIComponent(vehicle.vehicle_id) + "/status", function(status) {
                    var drift = status.mission_drift || null
                    if (!drift) {
                        missionLabel = "Mission not checked"
                    } else if (drift.classification === "NO_CHANGE") {
                        missionLabel = "Mission: matches"
                    } else {
                        missionLabel = "Mission: " + (drift.classification || "drift")
                    }
                    var operations = status.operations || []
                    if (operations.length === 0) {
                        operationLabel = "No operation"
                        return
                    }
                    var operation = operations[operations.length - 1]
                    var state = operation.state || {}
                    operationLabel = (state.declaration || "UNKNOWN") + " · "
                            + (state.telemetry_publication || "NOT_STARTED")
                }, endpoint)
            }, endpoint)
        }, root.connectorBaseUrl)
    }

    Timer {
        interval: 2500
        repeat: true
        running: true
        onTriggered: root.refreshStatus()
    }

    Component.onCompleted: refreshStatus()

    QGCToolInsets {
        id: toolInsets
        leftEdgeTopInset: parentToolInsets.leftEdgeTopInset
        leftEdgeCenterInset: parentToolInsets.leftEdgeCenterInset
        leftEdgeBottomInset: parentToolInsets.leftEdgeBottomInset
        rightEdgeTopInset: parentToolInsets.rightEdgeTopInset + statusCard.width + 12
        rightEdgeCenterInset: parentToolInsets.rightEdgeCenterInset
        rightEdgeBottomInset: parentToolInsets.rightEdgeBottomInset
        topEdgeLeftInset: parentToolInsets.topEdgeLeftInset
        topEdgeCenterInset: parentToolInsets.topEdgeCenterInset
        topEdgeRightInset: parentToolInsets.topEdgeRightInset
        bottomEdgeLeftInset: parentToolInsets.bottomEdgeLeftInset
        bottomEdgeCenterInset: parentToolInsets.bottomEdgeCenterInset
        bottomEdgeRightInset: parentToolInsets.bottomEdgeRightInset
    }

    Rectangle {
        id: statusCard
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 12
        anchors.rightMargin: 12
        width: 236
        height: 144
        radius: 6
        color: qgcPal.windowShade
        border.color: connectorOnline ? qgcPal.colorGreen : qgcPal.warningText
        border.width: 1
        opacity: 0.96

        Column {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 3

            Text {
                text: "UTM CONNECTOR"
                color: qgcPal.text
                font.bold: true
                font.pixelSize: 12
            }

            Text {
                text: root.connectorLabel
                color: root.connectorOnline ? qgcPal.colorGreen : qgcPal.warningText
                font.pixelSize: 12
                elide: Text.ElideRight
                width: parent.width
            }

            Text {
                text: root.vehicleLabel
                color: qgcPal.text
                font.pixelSize: 11
                elide: Text.ElideRight
                width: parent.width
            }

            Text {
                text: root.missionLabel
                color: root.missionLabel === "Mission: matches" ? qgcPal.colorGreen : qgcPal.text
                font.pixelSize: 10
                elide: Text.ElideRight
                width: parent.width
            }

            Text {
                text: "Operation: " + root.operationLabel
                color: qgcPal.text
                font.pixelSize: 10
                elide: Text.ElideRight
                width: parent.width
            }

            QGCButton {
                text: "Open UTM console"
                height: 26
                onClicked: Qt.openUrlExternally(root.resolvedConnectorBaseUrl + "/ui/")
            }
        }
    }
}
