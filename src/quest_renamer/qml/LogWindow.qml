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

    function openWindow() {
        show()
        raise()
        requestActivate()
    }

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
                onClicked: appController.openLogFile()
            }
            AppButton {
                text: "Copy support info"
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
                onClicked: appController.clearActivity()
            }
            AppButton {
                text: "Close"
                onClicked: root.hide()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: "#353535"
        }

        TextArea {
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: appController.activityDisplayText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            color: "#c7c7c7"
            selectionColor: "#4c8abb"
            selectedTextColor: "#ffffff"
            font.family: "monospace"
            font.pixelSize: 11
            leftPadding: 16
            rightPadding: 16
            topPadding: 14
            bottomPadding: 14
            background: Rectangle { color: "#171717" }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            color: "#1b1b1b"
            border.width: 1
            border.color: "#303030"
            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                text: appController.logPath
                color: "#777777"
                font.pixelSize: 9
                elide: Text.ElideMiddle
            }
        }
    }
}
