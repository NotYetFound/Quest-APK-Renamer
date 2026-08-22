import QtQuick
import QtQuick.Controls

// Desktop-style vertical scroller: the mouse wheel moves a fixed number of pixels
// per notch with no kinetic overshoot, touchpads scroll by their pixel delta, and
// the scroll bar stays usable. Declare the page content as a child and point
// ``page`` at it so the content height follows its implicit height.
Flickable {
    id: flick
    property Item page: null
    property int topInset: 16
    property int bottomInset: 28
    property int wheelStep: 84

    contentWidth: width
    contentHeight: page ? page.implicitHeight + topInset + bottomInset : 0
    clip: true
    // Wheel and scroll bar only; dragging the page with the mouse is not a desktop idiom.
    interactive: false
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: AppScrollBar { id: bar }
    activeFocusOnTab: false

    function scrollBy(delta) {
        var limit = Math.max(0, contentHeight - height)
        contentY = Math.max(0, Math.min(limit, contentY + delta))
    }

    onHeightChanged: scrollBy(0)
    onContentHeightChanged: scrollBy(0)

    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: event => {
            var delta = event.pixelDelta.y !== 0
                      ? event.pixelDelta.y
                      : (event.angleDelta.y / 120) * flick.wheelStep
            flick.scrollBy(-delta)
            event.accepted = true
        }
    }

    Keys.onPressed: event => {
        if (event.key === Qt.Key_PageDown) { scrollBy(height * 0.9); event.accepted = true }
        else if (event.key === Qt.Key_PageUp) { scrollBy(-height * 0.9); event.accepted = true }
        else if (event.key === Qt.Key_Home) { contentY = 0; event.accepted = true }
        else if (event.key === Qt.Key_End) { scrollBy(contentHeight); event.accepted = true }
    }
}
