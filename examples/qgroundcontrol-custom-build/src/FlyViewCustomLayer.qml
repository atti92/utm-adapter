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
    property bool connectorOnline: false
    property string connectorLabel: "UTM offline"
    property string vehicleLabel: "No vehicle"

    function setOffline(label) {
        connectorOnline = false
        connectorLabel = label || "UTM offline"
        vehicleLabel = "No vehicle"
    }

    function requestJson(path, callback) {
        var request = new XMLHttpRequest()
        request.open("GET", connectorBaseUrl + path)
        request.onreadystatechange = function() {
            if (request.readyState !== 4) {
                return
            }
            if (request.status < 200 || request.status >= 300) {
                setOffline("UTM unavailable")
                return
            }
            try {
                callback(JSON.parse(request.responseText))
            } catch (error) {
                setOffline("UTM response error")
            }
        }
        request.onerror = function() { setOffline("UTM unavailable") }
        request.send()
    }

    function refreshStatus() {
        requestJson("/v1/health", function(health) {
            connectorOnline = health.status === "ok"
            connectorLabel = connectorOnline
                    ? "UTM ready"
                    : (health.backend_error ? "Provider degraded" : "UTM degraded")
            requestJson("/v1/vehicles", function(vehicles) {
                if (vehicles.length === 0) {
                    vehicleLabel = "No vehicle telemetry"
                    return
                }
                var vehicle = vehicles[0]
                vehicleLabel = vehicle.vehicle_id + " · " + (vehicle.quality || "unknown")
            })
        })
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
        height: 104
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

            QGCButton {
                text: "Open UTM console"
                height: 26
                onClicked: Qt.openUrlExternally(root.connectorBaseUrl + "/ui/")
            }
        }
    }
}
