import QtQuick
import QtQuick.Layouts

Item {
    id: tour
    property int step: 0
    property Item target: null
    property Item endTarget: null
    property int stepCount: 6
    property string advanceText: ""
    property string hint: ""
    property bool advanceEnabled: true
    property string errorText: ""
    property bool showToolsAction: false
    property bool showSourceHelp: false
    signal advance()
    signal exitTour()
    signal openTools()
    signal openSourceHelp()
    visible: step > 0 && target !== null

    // Read the ancestors' positions so scrolling and resizing update the highlight.
    function itemRect(control) {
        for (let item = control; item && item !== tour; item = item.parent) {
            const position = item.x + item.y + item.width + item.height
        }
        const point = control.mapToItem(tour, 0, 0)
        return Qt.rect(point.x, point.y, control.width, control.height)
    }
    function targetRect() {
        if (!target || !visible)
            return Qt.rect(0, 0, 0, 0)
        const first = itemRect(target)
        const last = endTarget ? itemRect(endTarget) : first
        const left = Math.min(first.x, last.x)
        const top = Math.min(first.y, last.y)
        return Qt.rect(left - 5, top - 5,
                       Math.max(first.x + first.width, last.x + last.width) - left + 10,
                       Math.max(first.y + first.height, last.y + last.height) - top + 10)
    }
    readonly property rect bounds: targetRect()

    Item {
        id: spotlight
        x: tour.bounds.x
        y: tour.bounds.y
        width: tour.bounds.width
        height: tour.bounds.height
        Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Rectangle { anchors.fill: parent; color: "transparent"; border.color: "#73b9f4"; border.width: 2; radius: 6 }
    }

    Rectangle { width: tour.width; height: Math.max(0, spotlight.y); color: "#65000000" }
    Rectangle { y: spotlight.y + spotlight.height; width: tour.width; height: Math.max(0, tour.height - y); color: "#65000000" }
    Rectangle { y: spotlight.y; width: Math.max(0, spotlight.x); height: spotlight.height; color: "#65000000" }
    Rectangle { x: spotlight.x + spotlight.width; y: spotlight.y; width: Math.max(0, tour.width - x); height: spotlight.height; color: "#65000000" }

    Rectangle {
        width: Math.min(tour.step === 3 ? 390 : 340, tour.width - 24)
        height: card.implicitHeight + 24
        x: Math.max(12, Math.min(tour.width - width - 12, spotlight.x))
        y: spotlight.y + spotlight.height + height + 12 <= tour.height
           ? spotlight.y + spotlight.height + 10 : Math.max(12, spotlight.y - height - 10)
        color: "#22242b"
        border.color: "#73b9f4"
        radius: 6
        // Only the card takes clicks; the real dashboard controls stay usable.
        MouseArea { anchors.fill: parent }
        ColumnLayout {
            id: card
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 12
            Text {
                text: "Tutorial · " + tour.step + " of " + tour.stepCount
                color: "#a6c6e3"
                font.pixelSize: 11
            }
            Text {
                Layout.fillWidth: true
                text: tour.errorText || tour.hint
                wrapMode: Text.WordWrap
                color: tour.errorText ? "#f2a49f" : "#f1f1f1"
                font.pixelSize: 13
                textFormat: Text.PlainText
                maximumLineCount: tour.errorText ? 7 : 20
                elide: Text.ElideRight
                Accessible.name: text
            }
            RowLayout {
                Layout.fillWidth: true
                AppButton { visible: tour.step < tour.stepCount; text: "Exit tutorial"; quiet: true; onClicked: tour.exitTour() }
                Item { Layout.fillWidth: true }
                AppButton {
                    visible: tour.showSourceHelp
                    text: "More info"
                    onClicked: tour.openSourceHelp()
                }
                AppButton {
                    visible: tour.showToolsAction
                    text: "Open tool settings"
                    primary: true
                    onClicked: tour.openTools()
                }
                AppButton {
                    visible: !tour.errorText && tour.advanceText.length > 0
                    enabled: tour.advanceEnabled
                    text: tour.advanceText
                    primary: true
                    onClicked: tour.advance()
                }
            }
        }
    }
}
