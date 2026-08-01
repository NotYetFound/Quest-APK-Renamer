import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "inspectorPage"
    property color textPrimary: "#eeeeee"
    property color textSecondary: "#939393"
    property color line: "#353535"
    property color panel: "#1f1f1f"
    property color accent: "#4c8abb"
    property int tabIndex: 0

    Connections {
        target: fileDialogController
        function onFileSelected(purpose, url) {
            if (purpose === "inspectApk")
                inspectorController.inspectApk(url)
        }
        function onSaveSelected(purpose, url) {
            if (purpose === "inspectionExport")
                inspectorController.exportAnalysis(url)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 26
        anchors.rightMargin: 26
        anchors.topMargin: 16
        anchors.bottomMargin: 26
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Item { Layout.fillWidth: true }
            AppButton {
                text: "Use Dashboard APK"
                enabled: appController.hasBundle
                         && !inspectorController.isBusy
                         && !appController.isBusy
                         && !bulkController.isBusy
                onClicked: inspectorController.inspectPath(appController.apkPath)
            }
            AppButton {
                text: "Choose APK…"
                primary: !inspectorController.hasAnalysis
                enabled: !inspectorController.isBusy
                         && !appController.isBusy
                         && !bulkController.isBusy
                onClicked: fileDialogController.chooseApk(
                    "inspectApk",
                    "Choose an APK to inspect",
                    inspectorController.apkPath
                )
            }
            AppButton {
                visible: inspectorController.isBusy
                text: "Cancel safely"
                onClicked: inspectorController.cancel()
            }
            AppButton {
                visible: inspectorController.hasAnalysis && !inspectorController.isBusy
                text: "Export JSON…"
                onClicked: fileDialogController.saveJson(
                    "inspectionExport",
                    "Export " + inspectorController.exportFileName,
                    inspectorController.exportFileName,
                    inspectorController.apkPath
                )
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 92
            radius: 3
            color: inspectorDrop.containsDrag ? "#252525" : root.panel
            border.width: 1
            border.color: inspectorDrop.containsDrag ? root.accent : root.line
            Behavior on color { ColorAnimation { duration: 100 } }

            DropArea {
                id: inspectorDrop
                anchors.fill: parent
                onDropped: drop => {
                    if (drop.hasUrls && drop.urls.length > 0)
                        inspectorController.inspectApk(drop.urls[0])
                }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: inspectorController.title
                        color: inspectorController.apkPath ? root.textPrimary : "#777777"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: inspectorController.packageName
                        color: "#8b8b8b"
                        font.pixelSize: 11
                        elide: Text.ElideMiddle
                    }
                    BusyIndicator {
                        visible: inspectorController.isBusy
                        running: visible
                        Layout.preferredWidth: 20
                        Layout.preferredHeight: 20
                        Accessible.name: "APK inspection in progress"
                    }
                    Rectangle {
                        visible: inspectorController.hasAnalysis
                        implicitWidth: signerText.implicitWidth + 18
                        implicitHeight: 25
                        radius: 12
                        color: inspectorController.signerTone === "success" ? "#263c32"
                             : inspectorController.signerTone === "warning" ? "#443b25"
                             : "#303030"
                        Text {
                            id: signerText
                            anchors.centerIn: parent
                            text: inspectorController.signerLabel
                            color: inspectorController.signerTone === "success" ? "#a8d3b9"
                                 : inspectorController.signerTone === "warning" ? "#d9c27c"
                                 : "#b5b5b5"
                            font.pixelSize: 10
                            font.weight: Font.Medium
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: inspectorController.hasAnalysis
                          ? inspectorController.summary
                          : (inspectorController.apkPath || "Drop one APK here to inspect it.")
                    color: "#858585"
                    font.pixelSize: 10
                    elide: Text.ElideMiddle
                }
                Text {
                    Layout.fillWidth: true
                    text: inspectorController.status
                          + (inspectorController.isBusy
                             ? "  " + Math.round(inspectorController.progress * 100) + "%"
                             : "")
                    color: inspectorController.tone === "success" ? "#70b18f"
                         : inspectorController.tone === "warning" ? "#d0b15b"
                         : inspectorController.tone === "error" ? "#d4776f"
                         : "#888888"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                visible: inspectorController.isBusy
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 2
                color: "#303030"
                Rectangle {
                    width: parent.width * inspectorController.progress
                    height: parent.height
                    color: root.accent
                    Behavior on width { NumberAnimation { duration: 100 } }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 3
            color: root.panel
            border.width: 1
            border.color: root.line

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                TabBar {
                    id: tabs
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42
                    currentIndex: root.tabIndex
                    visible: inspectorController.hasAnalysis
                    background: Rectangle { color: "#1c1c1c" }
                    onCurrentIndexChanged: root.tabIndex = currentIndex

                    Repeater {
                        model: ["Overview", "Signing", "Permissions", "Rename preview"]
                        TabButton {
                            id: tabButton
                            required property string modelData
                            text: modelData
                            contentItem: Text {
                                text: tabButton.text
                                color: tabButton.checked ? root.textPrimary : "#858585"
                                font.pixelSize: 11
                                font.weight: tabButton.checked ? Font.DemiBold : Font.Normal
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle {
                                color: tabButton.checked ? "#252525" : "transparent"
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    height: tabButton.checked ? 2 : 0
                                    color: root.accent
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: inspectorController.hasAnalysis ? 1 : 0
                    color: root.line
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: !inspectorController.hasAnalysis
                    Column {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 80, 470)
                        spacing: 9
                        Text {
                            width: parent.width
                            text: inspectorController.isBusy ? "Inspecting APK…" : "No inspection results yet"
                            color: root.textPrimary
                            font.pixelSize: 17
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            width: parent.width
                            text: inspectorController.isBusy
                                  ? "The APK is being decoded in a temporary workspace. The source file stays untouched."
                                  : "Choose one APK, use the Dashboard selection, or drop a file above."
                            color: root.textSecondary
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            lineHeight: 1.25
                        }
                    }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: inspectorController.hasAnalysis
                    currentIndex: root.tabIndex

                    ScrollView {
                        contentWidth: availableWidth
                        clip: true
                        ColumnLayout {
                            width: parent.width
                            spacing: 0
                            Repeater {
                                model: inspectorController.overviewRows
                                delegate: InspectorValueRow {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    label: modelData.label
                                    value: modelData.value
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.leftMargin: 18
                                Layout.rightMargin: 18
                                Layout.topMargin: 16
                                Layout.bottomMargin: 5
                                text: "FILE HASHES"
                                color: "#777777"
                                font.pixelSize: 9
                                font.weight: Font.DemiBold
                                font.letterSpacing: 1
                            }
                            Repeater {
                                model: inspectorController.hashRows
                                delegate: InspectorValueRow {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    label: modelData.label
                                    value: modelData.value
                                    monospace: true
                                }
                            }
                        }
                    }

                    ScrollView {
                        contentWidth: availableWidth
                        clip: true
                        ColumnLayout {
                            width: parent.width
                            spacing: 0
                            Repeater {
                                model: inspectorController.signingRows
                                delegate: InspectorValueRow {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    label: modelData.label
                                    value: modelData.value
                                    monospace: modelData.label.indexOf("SHA") >= 0
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        spacing: 0
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 36
                            color: "#1c1c1c"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                Text { text: "TYPE"; color: "#777777"; font.pixelSize: 9; Layout.preferredWidth: 90 }
                                Text { text: "PERMISSION OR FEATURE"; color: "#777777"; font.pixelSize: 9; Layout.fillWidth: true }
                                Text { text: "REQUIRED"; color: "#777777"; font.pixelSize: 9; Layout.preferredWidth: 70; horizontalAlignment: Text.AlignRight }
                            }
                        }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: inspectorController.permissionRows
                            delegate: Rectangle {
                                id: permissionRow
                                required property var modelData
                                required property int index
                                width: ListView.view.width
                                height: 36
                                color: index % 2 ? "#202020" : "#222222"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    Text { text: permissionRow.modelData.kind; color: "#8d8d8d"; font.pixelSize: 10; Layout.preferredWidth: 90 }
                                    Text { text: permissionRow.modelData.name; color: "#cccccc"; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                    Text { text: permissionRow.modelData.required; color: "#a0a0a0"; font.pixelSize: 10; Layout.preferredWidth: 70; horizontalAlignment: Text.AlignRight }
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        spacing: 0
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: inspectorController.nativeWarning ? 70 : 48
                            color: "#1c1c1c"
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 3
                                Text { text: inspectorController.referenceSummary; color: "#bdbdbd"; font.pixelSize: 11 }
                                Text {
                                    Layout.fillWidth: true
                                    visible: inspectorController.nativeWarning
                                    text: inspectorController.nativeWarning
                                    color: "#d0b15b"
                                    font.pixelSize: 9
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            color: "#222222"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                Text { text: "ACTION"; color: "#777777"; font.pixelSize: 9; Layout.preferredWidth: 70 }
                                Text { text: "FILE"; color: "#777777"; font.pixelSize: 9; Layout.fillWidth: true }
                                Text { text: "REFERENCES"; color: "#777777"; font.pixelSize: 9; Layout.preferredWidth: 76; horizontalAlignment: Text.AlignRight }
                            }
                        }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: inspectorController.referenceRows
                            delegate: Rectangle {
                                id: referenceRow
                                required property var modelData
                                required property int index
                                width: ListView.view.width
                                height: 36
                                color: index % 2 ? "#202020" : "#222222"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    Text {
                                        text: referenceRow.modelData.action
                                        color: referenceRow.modelData.action === "Update" ? "#70b18f" : "#d0b15b"
                                        font.pixelSize: 10
                                        font.weight: Font.Medium
                                        Layout.preferredWidth: 70
                                    }
                                    Text { text: referenceRow.modelData.path; color: "#cccccc"; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideMiddle }
                                    Text { text: referenceRow.modelData.count; color: "#a0a0a0"; font.pixelSize: 10; Layout.preferredWidth: 76; horizontalAlignment: Text.AlignRight }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
