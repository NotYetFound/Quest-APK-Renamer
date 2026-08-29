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
    Accessible.role: Accessible.CheckBox
    Accessible.name: title
    Accessible.description: detail

    RowLayout {
        anchors.fill: parent
        spacing: compact ? 10 : 18
        ColumnLayout {
            Layout.fillWidth: true
            spacing: root.compact ? 1 : 3
            Text {
                Layout.fillWidth: true
                text: root.title
                color: root.enabled ? "#e2e2e2" : "#8f8f8f"
                font.pixelSize: root.compact ? 11 : 13
                font.weight: Font.Medium
                elide: Text.ElideRight
            }
            Text {
                text: root.detail
                color: "#848484"
                font.pixelSize: root.compact ? 9 : 11
                Layout.fillWidth: true
                elide: Text.ElideRight
                ToolTip.visible: detailMouse.containsMouse && truncated
                ToolTip.text: root.detail
                ToolTip.delay: 400
                MouseArea {
                    id: detailMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }
            }
        }
        AppSwitch {
            id: toggle
            compact: root.compact
            Accessible.name: root.title
            onToggled: root.changed(checked)
        }
    }

    MouseArea {
        // Clicking the label toggles the switch, like a native form row.
        anchors.fill: parent
        anchors.rightMargin: toggle.width + 12
        enabled: root.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            toggle.toggle()
            root.changed(toggle.checked)
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: "#2d2d34"
    }
}
