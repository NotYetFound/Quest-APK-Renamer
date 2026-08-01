import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property string title: ""
    property string detail: ""
    property alias checked: toggle.checked
    property bool compact: false
    signal changed(bool value)
    implicitHeight: compact ? 42 : 64

    RowLayout {
        anchors.fill: parent
        spacing: compact ? 10 : 18
        ColumnLayout {
            Layout.fillWidth: true
            spacing: root.compact ? 1 : 3
            Text {
                text: root.title
                color: "#e2e2e2"
                font.pixelSize: root.compact ? 11 : 13
                font.weight: Font.Medium
            }
            Text {
                text: root.detail
                color: "#848484"
                font.pixelSize: root.compact ? 9 : 11
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
        }
        Switch {
            id: toggle
            Layout.preferredWidth: root.compact ? 36 : 42
            Layout.preferredHeight: root.compact ? 20 : 24
            indicator: Rectangle {
                implicitWidth: root.compact ? 32 : 38
                implicitHeight: root.compact ? 18 : 22
                x: toggle.leftPadding
                y: parent.height / 2 - height / 2
                radius: 11
                color: toggle.checked ? "#3478b1" : "#383838"
                border.width: 1
                border.color: toggle.checked ? "#4a8bc0" : "#505050"
                Behavior on color { ColorAnimation { duration: 120 } }
                Rectangle {
                    x: toggle.checked ? parent.width - width - 3 : 3
                    y: 3
                    width: root.compact ? 12 : 16
                    height: root.compact ? 12 : 16
                    radius: 8
                    color: "#f0f3f6"
                    Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
                }
            }
            onToggled: root.changed(checked)
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: "#333333"
    }
}
