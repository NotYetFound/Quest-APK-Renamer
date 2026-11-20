import QtQuick

// Shared desktop scrolling for pages and virtualized lists.
WheelHandler {
    required property Flickable viewport
    property int wheelStep: 240
    property real pixelScrollScale: 2.0
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    onWheel: event => {
        const pixels = event.pixelDelta.x !== 0 || event.pixelDelta.y !== 0
        const delta = pixels ? event.pixelDelta.y * pixelScrollScale
                             : event.angleDelta.y / 120 * wheelStep
        viewport.cancelFlick()
        const limit = Math.max(0, viewport.contentHeight - viewport.height)
        viewport.contentY = Math.max(0, Math.min(limit, viewport.contentY - delta))
        event.accepted = true
    }
}
