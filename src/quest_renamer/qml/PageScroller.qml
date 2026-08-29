import QtQuick
import QtQuick.Controls
import QtQuick.Window

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

    // Keyboard users tab through controls that may sit below the fold; bring the
    // focused one into view the way a native scroll area does.
    function ensureVisible(item) {
        if (!item || !flick.page)
            return
        var ancestor = item
        while (ancestor && ancestor !== flick)
            ancestor = ancestor.parent
        if (ancestor !== flick)
            return
        var top = item.mapToItem(flick.contentItem, 0, 0).y
        var bottom = top + item.height
        var limit = Math.max(0, flick.contentHeight - flick.height)
        if (top < flick.contentY + 8)
            flick.contentY = Math.max(0, Math.min(limit, top - 16))
        else if (bottom > flick.contentY + flick.height - 8)
            flick.contentY = Math.max(0, Math.min(limit, bottom - flick.height + 16))
    }

    Connections {
        target: flick.Window.window
        function onActiveFocusItemChanged() {
            var focused = flick.Window.window ? flick.Window.window.activeFocusItem : null
            if (focused)
                flick.ensureVisible(focused)
        }
    }

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
