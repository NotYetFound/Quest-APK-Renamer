import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool quiet: false
    property bool danger: false

    implicitHeight: 38
    leftPadding: 14
    rightPadding: 14
    font.pixelSize: 14
    font.weight: Font.DemiBold
    focusPolicy: Qt.StrongFocus
    Accessible.name: text

    contentItem: Text {
        text: control.text
        font: control.font
        color: !control.enabled ? "#777777"
              : control.primary || control.danger ? "#ffffff"
              : "#e3e3e3"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: 3
        color: !control.enabled ? "#242424"
              : control.down ? (control.danger ? "#66332f" : control.primary ? "#285f8d" : "#292929")
              : control.hovered ? (control.danger ? "#884842" : control.primary ? "#3e82bb" : "#333333")
              : control.danger ? "#76403b"
              : control.primary ? "#3478b1"
              : control.quiet ? "transparent"
              : "#2b2b2b"
        border.width: control.activeFocus || !(control.primary || control.danger || control.quiet) ? 1 : 0
        border.color: control.activeFocus ? "#79a9cf" : "#464646"

        Behavior on color { ColorAnimation { duration: 100 } }
    }
}
