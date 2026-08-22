import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property string label: ""
    property string value: ""
    property bool monospace: false
    implicitHeight: Math.max(42, valueText.implicitHeight + 18)

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        spacing: 18
        Text {
            text: root.label
            color: "#888888"
            font.pixelSize: 10
            Layout.preferredWidth: 150
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 12
        }
        TextEdit {
            id: valueText
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 10
            Layout.bottomMargin: 8
            text: root.value
            color: "#d0d0d0"
            font.pixelSize: 10
            font.family: !root.monospace ? Qt.application.font.family
                       : Qt.platform.os === "windows" ? "Consolas"
                       : Qt.platform.os === "osx" ? "Menlo"
                       : "monospace"
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: "#303030"
    }
}
