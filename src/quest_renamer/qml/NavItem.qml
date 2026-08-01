import QtQuick
import QtQuick.Controls

Button {
    id: control
    property string label: ""
    property string glyph: ""
    property bool selected: false

    implicitHeight: 40
    leftPadding: 12
    rightPadding: 10
    focusPolicy: Qt.StrongFocus
    Accessible.name: label
    Accessible.description: selected ? "Current page" : "Open page"

    contentItem: Row {
        spacing: 11
        Text {
            width: 18
            anchors.verticalCenter: parent.verticalCenter
            text: control.glyph
            color: control.selected ? "#d7d7d7" : "#858585"
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: control.label
            color: control.selected ? "#f0f0f0" : "#a9a9a9"
            font.pixelSize: 13
            font.weight: control.selected ? Font.DemiBold : Font.Medium
        }
    }

    background: Rectangle {
        radius: 2
        color: control.selected ? "#272727"
              : control.activeFocus ? "#252525"
              : control.hovered ? "#222222"
              : "transparent"
        Behavior on color { ColorAnimation { duration: 110 } }

        Rectangle {
            visible: control.selected || control.activeFocus
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 2
            color: control.activeFocus ? "#79a9cf" : "#4c8abb"
        }
    }
}
