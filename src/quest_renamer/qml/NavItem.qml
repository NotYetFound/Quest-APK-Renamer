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
    topPadding: 0
    bottomPadding: gapHitHeight
    focusPolicy: Qt.TabFocus
    Accessible.name: label
    Accessible.description: selected ? "Current page" : "Open page"

    // Icon and label share one vertical centre inside the visible 40 px row; the
    // glyph is nudged 1 px down so it lines up with the optical centre of the text.
    contentItem: Item {
        implicitHeight: control.visualHeight
        implicitWidth: 20 + 9 + navLabel.implicitWidth
        IconImage {
            id: navIcon
            width: 16
            height: 16
            x: 2
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: 1
            source: control.iconSource
            color: control.selected ? "#d7d7d7" : "#858585"
            sourceSize.width: 16
            sourceSize.height: 16
        }
        Text {
            id: navLabel
            x: 29
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
        color: control.selected ? "#222227"
              : control.activeFocus ? "#202025"
              : rowHover.hovered ? "#1d1d21"
              : "transparent"
        // Only the visible row reacts to the pointer; the 3 px hit gap below each
        // row belongs to the button for clicks but must not light it up.
        HoverHandler { id: rowHover }

        Rectangle {
            visible: control.selected || control.activeFocus
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 2
            color: control.activeFocus ? "#7fb2dd" : "#4b90cc"
        }
    }
}
