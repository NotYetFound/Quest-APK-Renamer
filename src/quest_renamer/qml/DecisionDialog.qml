import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: popup
    property string heading: ""
    property string bodyText: ""
    property string primaryText: "Continue"
    property string secondaryText: "Cancel"
    property string tertiaryText: ""
    property bool destructive: false
    property bool actionTaken: false
    signal primaryChosen()
    signal secondaryChosen()
    signal tertiaryChosen()
    signal dismissed()

    parent: Overlay.overlay
    x: Math.round((parent.width - width) / 2)
    y: Math.round((parent.height - height) / 2)
    width: Math.min(460, parent.width - 48)
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape

    onOpened: {
        actionTaken = false
        if (popup.destructive)
            secondaryButton.forceActiveFocus()
        else
            primaryButton.forceActiveFocus()
    }
    onClosed: {
        if (!actionTaken)
            dismissed()
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 130 }
            NumberAnimation { property: "scale"; from: 0.98; to: 1; duration: 150; easing.type: Easing.OutCubic }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 90 }
    }

    background: Rectangle {
        radius: 4
        color: "#242424"
        border.width: 1
        border.color: "#4a4a4a"
    }

    contentItem: ColumnLayout {
        spacing: 0
        Accessible.name: popup.heading
        Accessible.description: popup.bodyText

        ColumnLayout {
            Layout.fillWidth: true
            Layout.margins: 20
            spacing: 9
            Text {
                Layout.fillWidth: true
                text: popup.heading
                color: "#f0f0f0"
                font.pixelSize: 17
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: popup.bodyText
                color: "#aaaaaa"
                font.pixelSize: 12
                lineHeight: 1.25
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: "#393939"
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 12
            spacing: 8
            AppButton {
                visible: popup.tertiaryText.length > 0
                text: popup.tertiaryText
                quiet: true
                onClicked: {
                    popup.actionTaken = true
                    popup.tertiaryChosen()
                    popup.close()
                }
            }
            Item { Layout.fillWidth: true }
            AppButton {
                id: secondaryButton
                text: popup.secondaryText
                onClicked: {
                    popup.actionTaken = true
                    popup.secondaryChosen()
                    popup.close()
                }
            }
            AppButton {
                id: primaryButton
                text: popup.primaryText
                primary: !popup.destructive
                danger: popup.destructive
                onClicked: {
                    popup.actionTaken = true
                    popup.primaryChosen()
                    popup.close()
                }
            }
        }
    }
}
