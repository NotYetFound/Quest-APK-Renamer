import QtQuick

Item {
    id: root
    property int number: 1
    property string label: ""
    property string detail: ""
    property bool active: false
    property bool complete: false

    implicitHeight: 72

    Rectangle {
        id: marker
        width: 26
        height: 26
        radius: 13
        anchors.left: parent.left
        anchors.top: parent.top
        color: root.active ? "#1468b3" : root.complete ? "#244d3f" : "#222c37"
        border.width: root.active ? 0 : 1
        border.color: root.complete ? "#3e8b70" : "#3a4653"

        Text {
            anchors.centerIn: parent
            text: root.complete ? "✓" : root.number
            color: root.active ? "white" : root.complete ? "#9ee0c7" : "#9aa6b2"
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
    }

    Column {
        anchors.left: marker.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: 4

        Text {
            width: parent.width
            text: root.label
            color: root.active ? "#f1f4f7" : "#b2bdc8"
            font.pixelSize: 14
            font.weight: root.active ? Font.DemiBold : Font.Medium
        }
        Text {
            width: parent.width
            text: root.detail
            color: "#788593"
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }
}
