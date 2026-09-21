// UTM connector Fly View overlay for a QGroundControl custom build.
// It submits UTM data and operation intents, but never sends flight-control
// commands. QGroundControl/autopilot remain the flight-control authority.

import QtQuick
import QtQuick.Controls
import QGroundControl
import QGroundControl.Controls
import QGroundControl.FlyView
import QGroundControl.FlightMap
import Custom.Widgets

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
    property string selectedVehicleId: ""
    property string operationId: ""
    property string declarationState: ""
    property string telemetryPublicationState: "NOT_STARTED"
    property string actionMessage: ""
    property bool missionSubmitted: false
    property bool actionBusy: false
    property var _activeVehicle: QGroundControl.multiVehicleManager.activeVehicle
    property var _planController: globals.planMasterControllerFlyView
    property var _utmConnector: QGroundControl.corePlugin.utmConnector

    function setOffline(label) {
        connectorOnline = false
        connectorLabel = label || "UTM offline"
        vehicleLabel = "No vehicle"
        missionLabel = "Mission not checked"
        operationLabel = "No operation"
        selectedVehicleId = ""
        operationId = ""
        declarationState = ""
        telemetryPublicationState = "NOT_STARTED"
    }

    function futureWindowStart() {
        return new Date(Math.ceil((Date.now() + 2 * 60 * 1000) / 60000) * 60000).toISOString()
    }

    function futureWindowEnd() {
        return new Date(Date.parse(root.futureWindowStart()) + 35 * 60 * 1000).toISOString()
    }

    function submitCurrentPlan() {
        if (!root._utmConnector || !root._planController || !root.selectedVehicleId) {
            actionMessage = "Connect a vehicle and the UTM connector first."
            return
        }
        actionBusy = true
        actionMessage = "Uploading current QGC plan…"
        root._utmConnector.submitCurrentPlan(root.resolvedConnectorBaseUrl,
                                             root._planController,
                                             root.selectedVehicleId,
                                             root.futureWindowStart(),
                                             root.futureWindowEnd(),
                                             30.0)
    }

    function sendIntent(command) {
        if (!root._utmConnector || !root.selectedVehicleId) {
            actionMessage = "Connect a vehicle and the UTM connector first."
            return
        }
        if (command === "SUBMIT_OPERATION" && !root.operationId) {
            root.operationId = root._utmConnector.newOperationId()
        }
        if (!root.operationId) {
            actionMessage = "Submit the mission to UTM first."
            return
        }
        actionBusy = true
        actionMessage = command.replace("_", " ") + "…"
        root._utmConnector.sendOperationIntent(root.resolvedConnectorBaseUrl,
                                               root.selectedVehicleId,
                                               root.operationId,
                                               command)
    }

    function operationIsTerminal() {
        return ["COMPLETED", "CANCELLED", "REJECTED"].indexOf(root.declarationState) >= 0
    }

    function operationIsActive() {
        return ["SUBMITTED", "ACCEPTED"].indexOf(root.declarationState) >= 0
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
                selectedVehicleId = vehicle.vehicle_id
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
                        operationId = ""
                        declarationState = ""
                        telemetryPublicationState = "NOT_STARTED"
                        return
                    }
                    var operation = operations[operations.length - 1]
                    var state = operation.state || {}
                    operationLabel = (state.declaration || "UNKNOWN") + " · "
                            + (state.telemetry_publication || "NOT_STARTED")
                    if (root.operationIsActiveState(state.declaration)) {
                        missionSubmitted = true
                        operationId = operation.operation_id || ""
                        declarationState = state.declaration || ""
                        telemetryPublicationState = state.telemetry_publication || "NOT_STARTED"
                    } else {
                        // Terminal operations are history. Keep the label for context,
                        // but allow this QGC plan to be submitted as a new operation.
                        operationId = ""
                        declarationState = ""
                        telemetryPublicationState = "NOT_STARTED"
                    }
                }, endpoint)
            }, endpoint)
        }, root.connectorBaseUrl)
    }

    function operationIsActiveState(declaration) {
        return ["SUBMITTED", "ACCEPTED"].indexOf(declaration) >= 0
    }

    Timer {
        interval: 2500
        repeat: true
        running: true
        onTriggered: root.refreshStatus()
    }

    Component.onCompleted: refreshStatus()

    Connections {
        target: root._utmConnector
        function onRequestFinished(success, message) {
            root.actionBusy = false
            root.actionMessage = message
            if (success) {
                root.missionSubmitted = root.missionSubmitted || message.indexOf("Mission upload") >= 0
                root.refreshStatus()
            }
        }
    }

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
        height: 296
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

            Text {
                text: root.actionMessage
                color: root.actionMessage.indexOf("failed") >= 0 || root.actionMessage.indexOf("required") >= 0
                       ? qgcPal.warningText : qgcPal.colorGreen
                font.pixelSize: 10
                elide: Text.ElideRight
                width: parent.width
                visible: text.length > 0
            }

            QGCButton {
                text: root.actionBusy ? "Working…"
                                      : (root.operationIsActive() ? "Finish active operation first"
                                      : (root.missionSubmitted ? "Submit new plan" : "Submit current plan"))
                enabled: !root.actionBusy && root.connectorOnline && !!root.selectedVehicleId
                         && !!root._planController && root._planController.containsItems && !root.operationIsActive()
                height: 26
                width: parent.width
                onClicked: root.submitCurrentPlan()
            }

            QGCButton {
                text: "Request UTM approval"
                visible: root.missionSubmitted && !root.operationId && !root.operationIsActive()
                enabled: !root.actionBusy && root.connectorOnline
                height: 26
                width: parent.width
                onClicked: root.sendIntent("SUBMIT_OPERATION")
            }

            QGCButton {
                text: "Start UTM telemetry"
                visible: !!root.operationId && root.declarationState === "ACCEPTED"
                         && root.telemetryPublicationState === "NOT_STARTED"
                enabled: !root.actionBusy && root.connectorOnline
                height: 26
                width: parent.width
                onClicked: root.sendIntent("START_OPERATION")
            }

            QGCButton {
                text: "Complete operation"
                visible: !!root.operationId && root.declarationState === "ACCEPTED"
                         && root.telemetryPublicationState === "ACTIVE"
                enabled: !root.actionBusy && root.connectorOnline
                height: 26
                width: parent.width
                onClicked: root.sendIntent("COMPLETE_OPERATION")
            }

            QGCButton {
                text: "Cancel operation"
                visible: !!root.operationId && !root.operationIsTerminal()
                enabled: !root.actionBusy && root.connectorOnline
                height: 26
                width: parent.width
                onClicked: root.sendIntent("CANCEL_OPERATION")
            }

            QGCButton {
                text: "Open UTM console"
                height: 26
                width: parent.width
                onClicked: Qt.openUrlExternally(root.resolvedConnectorBaseUrl + "/ui/")
            }
        }
    }
}
