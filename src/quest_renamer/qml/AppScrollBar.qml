import QtQuick
import QtQuick.Controls

// Slim scroll bar shared by every list and scrollable page.
ScrollBar {
    id: bar
    policy: ScrollBar.AsNeeded
    minimumSize: 0.08
    padding: 2
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: 3
        color: bar.pressed ? "#8a8a8a" : bar.hovered ? "#6a6a6a" : "#4a4a4a"
        opacity: bar.size >= 1 ? 0 : bar.active || bar.hovered ? 1 : 0.45
        Behavior on opacity { NumberAnimation { duration: 160 } }
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
