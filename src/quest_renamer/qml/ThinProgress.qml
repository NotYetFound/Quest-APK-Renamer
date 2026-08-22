import QtQuick

// Thin determinate progress bar; value is clamped to 0..1.
Rectangle {
    id: bar
    property real value: 0
    property color fillColor: "#4c8abb"
    property int thickness: 2
    implicitHeight: thickness
    height: thickness
    radius: thickness / 2
    color: "#303030"
    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, bar.value))
        height: parent.height
        radius: bar.radius
        color: bar.fillColor
        Behavior on width { NumberAnimation { duration: 120 } }
    }
}
