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
    property real pixelScrollScale: 1.0
    property bool scrollToMouseFocus: true

    contentWidth: width
    contentHeight: page ? page.implicitHeight + topInset + bottomInset : 0
    clip: true
    interactive: false
    flickableDirection: Flickable.VerticalFlick
    // Qt 6.9+ lets the native scroller accept wheel input without mouse dragging.
    Component.onCompleted: {
        if ("acceptedButtons" in flick)
            flick.acceptedButtons = Qt.NoButton
    }
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
            const control = focused as Control
            const field = focused as TextField
            const reason = control ? control.focusReason : field ? field.focusReason : undefined
            if (focused && (flick.scrollToMouseFocus || reason === Qt.TabFocusReason
                            || reason === Qt.BacktabFocusReason))
                flick.ensureVisible(focused)
        }
    }

    WheelHandler {
        target: null
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: event => {
            if (event.pixelDelta.x !== 0 || event.pixelDelta.y !== 0) {
                flick.scrollBy(-event.pixelDelta.y * flick.pixelScrollScale)
                event.accepted = true
                return
            }
            var delta = event.angleDelta.y !== 0
                      ? (event.angleDelta.y / 120) * flick.wheelStep
                      : 0
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
