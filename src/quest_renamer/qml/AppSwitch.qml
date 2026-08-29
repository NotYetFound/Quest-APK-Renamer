import QtQuick
import QtQuick.Controls

Switch {
    id: toggle
    property bool compact: false

    implicitWidth: compact ? 36 : 42
    implicitHeight: compact ? 20 : 24
    focusPolicy: Qt.StrongFocus
    padding: 0

    indicator: Rectangle {
        implicitWidth: toggle.compact ? 32 : 38
        implicitHeight: toggle.compact ? 18 : 22
        x: toggle.leftPadding
        y: parent.height / 2 - height / 2
        radius: 11
        color: !toggle.enabled ? "#28282e"
             : toggle.checked ? "#3580c2" : "#32323a"
        border.width: 1
        border.color: toggle.activeFocus ? "#7fb2dd"
                    : toggle.checked ? "#4b92cf" : "#494954"
        Behavior on color { ColorAnimation { duration: 120 } }
        Rectangle {
            x: toggle.checked ? parent.width - width - 3 : 3
            y: 3
            width: toggle.compact ? 12 : 16
            height: toggle.compact ? 12 : 16
            radius: 8
            color: toggle.enabled ? "#f0f3f6" : "#8a8a8a"
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
}
