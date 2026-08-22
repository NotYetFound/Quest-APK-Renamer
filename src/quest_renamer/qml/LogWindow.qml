import QtCore
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Window {
    id: root
    objectName: "logWindow"
    width: 820
    height: 560
    minimumWidth: 560
    minimumHeight: 360
    visible: false
    title: "Quest APK Renamer Logs"
    color: "#171717"

    // Keep the view pinned to the newest line unless the user scrolled up.
    property bool followTail: true

    Settings {
        category: "LogWindow"
        property alias x: root.x
        property alias y: root.y
        property alias width: root.width
        property alias height: root.height
    }

    function openWindow() {
        show()
        raise()
        requestActivate()
        if (root.followTail)
            logView.positionAtEnd()
    }

    Shortcut { sequences: ["Esc", StandardKey.Close]; onActivated: root.hide() }
    Shortcut { sequences: [StandardKey.Copy]; onActivated: logArea.copy() }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 54
            Layout.leftMargin: 16
            Layout.rightMargin: 10
            spacing: 8
            Text {
                text: "Logs"
                color: "#eeeeee"
                font.pixelSize: 17
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            AppButton {
                text: "Open log file"
                tip: "Open the full debug log in your default text editor"
                onClicked: appController.openLogFile()
            }
            AppButton {
                text: "Copy support info"
                tip: "Copy version, tool, and recent log details for a bug report"
                onClicked: appController.copySupportInformation()
            }
            AppButton {
                text: "Save copy…"
                onClicked: fileDialogController.saveLog(
                    "activityLog",
                    "Save a copy of the debug log",
                    appController.logExportFileName,
                    appController.logPath
                )
            }
            AppButton {
                text: "Clear"
                quiet: true
                tip: "Clear the visible log; the log file on disk is kept"
                onClicked: appController.clearActivity()
            }
            AppButton {
                text: "Close"
                tip: "Close this window (Esc)"
                onClicked: root.hide()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: "#353535"
        }

        ScrollView {
            id: logView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.vertical: AppScrollBar {
                id: logBar
                onPositionChanged: {
                    // The user pressed/wheeled away from the tail; stop following.
                    if (logBar.active)
                        root.followTail = logBar.position + logBar.size >= 0.995
                }
            }

            function positionAtEnd() {
                logBar.position = Math.max(0, 1 - logBar.size)
            }

            TextArea {
                id: logArea
                text: appController.activityDisplayText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: "#c7c7c7"
                selectionColor: "#4c8abb"
                selectedTextColor: "#ffffff"
                font.family: Qt.platform.os === "windows" ? "Consolas"
                           : Qt.platform.os === "osx" ? "Menlo"
                           : "monospace"
                font.pixelSize: 11
                leftPadding: 16
                rightPadding: 16
                topPadding: 14
                bottomPadding: 14
                background: Rectangle { color: "#171717" }
                onTextChanged: {
                    if (root.followTail && root.visible)
                        Qt.callLater(logView.positionAtEnd)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            color: "#1b1b1b"
            border.width: 1
            border.color: "#303030"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                spacing: 8
                Text {
                    Layout.fillWidth: true
                    text: appController.logPath
                    color: "#777777"
                    font.pixelSize: 9
                    elide: Text.ElideMiddle
                }
                Text {
                    visible: !root.followTail
                    text: "Paused — new lines below"
                    color: "#d0b15b"
                    font.pixelSize: 9
                }
                AppButton {
                    visible: !root.followTail
                    text: "Follow"
                    quiet: true
                    implicitHeight: 22
                    font.pixelSize: 10
                    leftPadding: 8
                    rightPadding: 8
                    onClicked: {
                        root.followTail = true
                        logView.positionAtEnd()
                    }
                }
            }
        }
    }
}
