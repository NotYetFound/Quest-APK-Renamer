import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool quiet: false
    property bool danger: false
    // Optional hover tooltip explaining what the action does.
    property string tip: ""

    implicitHeight: 38
    leftPadding: 14
    rightPadding: 14
    font.pixelSize: 14
    font.weight: Font.DemiBold
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    Accessible.description: tip

    // Disabled controls stop reporting ``hovered``; a handler keeps tracking so the
    // tooltip can still explain why a button is greyed out.
    HoverHandler { id: hoverTracker }
    ToolTip.visible: tip.length > 0 && (hovered || hoverTracker.hovered)
    ToolTip.text: tip
    ToolTip.delay: 500

    // The Basic style only activates buttons on Space; users expect Return as well.
    Keys.onReturnPressed: if (enabled) clicked()
    Keys.onEnterPressed: if (enabled) clicked()

    contentItem: Text {
        text: control.text
        font: control.font
        color: !control.enabled ? "#777777"
              : control.primary || control.danger ? "#ffffff"
              : "#e3e3e3"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 3
        color: !control.enabled ? "#1f1f24"
              : control.down ? (control.danger ? "#5c2c2b" : control.primary ? "#2a6699" : "#24242a")
              : control.hovered ? (control.danger ? "#7a3b39" : control.primary ? "#408bca" : "#2d2d34")
              : control.danger ? "#6a3533"
              : control.primary ? "#3580c2"
              : control.quiet ? "transparent"
              : "#26262c"
        border.width: control.activeFocus || !(control.primary || control.danger || control.quiet) ? 1 : 0
        border.color: control.activeFocus ? "#7fb2dd" : "#3f3f49"

        Behavior on color { ColorAnimation { duration: 100 } }
    }
}
