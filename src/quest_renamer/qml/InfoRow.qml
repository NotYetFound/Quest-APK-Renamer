import QtQuick

Item {
    id: root
    property string label: ""
    property string value: ""
    implicitHeight: 45

    Text {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        color: "#8f9ba8"
        font.pixelSize: 13
    }
    Text {
        anchors.left: parent.left
        anchors.leftMargin: 150
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.value
        color: "#e2e7ec"
        font.pixelSize: 13
        font.weight: Font.Medium
        elide: Text.ElideMiddle
        horizontalAlignment: Text.AlignRight
    }
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: "#252f3a"
    }
}
