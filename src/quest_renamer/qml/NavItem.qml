import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl

Button {
    id: control
    property string label: ""
    property url iconSource
    property bool selected: false
    readonly property int visualHeight: 40
    readonly property int gapHitHeight: 3

    implicitHeight: visualHeight + gapHitHeight
    leftPadding: 12
    rightPadding: 10
    bottomPadding: topPadding + gapHitHeight
    focusPolicy: Qt.StrongFocus
    Accessible.name: label
    Accessible.description: selected ? "Current page" : "Open page"

    contentItem: Row {
        spacing: 9
        Item {
            width: 20
            height: 18
            IconImage {
                width: 16
                height: 16
                anchors.centerIn: parent
                source: control.iconSource
                color: control.selected ? "#d7d7d7" : "#858585"
                sourceSize.width: 16
                sourceSize.height: 16
            }
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
        anchors.top: parent.top
        height: control.visualHeight
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
