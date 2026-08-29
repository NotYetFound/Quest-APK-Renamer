import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "inspectorPage"
    property color textPrimary: "#eeeeee"
    property color textSecondary: "#939393"
    property color line: "#2f2f36"
    property color panel: "#1a1a1e"
    property color accent: "#4b90cc"
    property int pageMargin: 30
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

    Connections {
        target: inspectorController
        // A fresh inspection always starts on the Overview tab.
        function onAnalysisChanged() {
            if (!inspectorController.hasAnalysis)
                root.tabIndex = 0
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: root.pageMargin
        anchors.rightMargin: root.pageMargin
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
                tip: "Inspect the APK currently selected on the Dashboard"
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
                    inspectorController.apkPath || appController.lastSourceFolder
                )
            }
            AppButton {
                visible: inspectorController.isBusy
                text: "Cancel safely"
                tip: "Stop the inspection at the next safe point"
                onClicked: inspectorController.cancel()
            }
            AppButton {
                visible: inspectorController.hasAnalysis && !inspectorController.isBusy
                text: "Copy summary"
                quiet: true
                tip: "Copy the overview and signing details as text"
                onClicked: inspectorController.copySummary()
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
            color: inspectorDrop.containsDrag ? "#202025" : root.panel
            border.width: 1
            border.color: inspectorDrop.containsDrag ? root.accent : root.line
            Behavior on color { ColorAnimation { duration: 100 } }

            DropArea {
                id: inspectorDrop
                anchors.fill: parent
                enabled: !inspectorController.isBusy
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
                        Layout.maximumWidth: root.width * 0.45
                        text: inspectorController.title
                        color: inspectorController.apkPath ? root.textPrimary : "#777777"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        elide: Text.ElideMiddle
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
                             : inspectorController.signerTone === "warning" ? "#3a3418"
                             : "#2b2b31"
                        Text {
                            id: signerText
                            anchors.centerIn: parent
                            text: inspectorController.signerLabel
                            color: inspectorController.signerTone === "success" ? "#a8d3b9"
                                 : inspectorController.signerTone === "warning" ? "#e8c45c"
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
                         : inspectorController.tone === "warning" ? "#e3b74a"
                         : inspectorController.tone === "error" ? "#e5706a"
                         : "#888888"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }

            ThinProgress {
                visible: inspectorController.isBusy
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                value: inspectorController.progress
                fillColor: root.accent
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
                    visible: inspectorController.hasAnalysis
                    background: Rectangle { color: "#17171a" }
                    // One-directional: the page owns tabIndex; the bar follows and reports clicks.
                    Binding { target: tabs; property: "currentIndex"; value: root.tabIndex }
                    onCurrentIndexChanged: if (root.tabIndex !== currentIndex) root.tabIndex = currentIndex

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
                                color: tabButton.checked ? "#202025" : "transparent"
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

                    PageScroller {
                        id: overviewScroll
                        page: overviewColumn
                        topInset: 0
                        bottomInset: 12
                        ColumnLayout {
                            id: overviewColumn
                            width: overviewScroll.width
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

                    PageScroller {
                        id: signingScroll
                        page: signingColumn
                        topInset: 0
                        bottomInset: 12
                        ColumnLayout {
                            id: signingColumn
                            width: signingScroll.width
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
                            color: "#17171a"
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
                            reuseItems: true
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: AppScrollBar {}
                            model: inspectorController.permissionRows
                            delegate: Rectangle {
                                id: permissionRow
                                required property var modelData
                                required property int index
                                width: ListView.view.width
                                height: 36
                                color: index % 2 ? "#1b1b1f" : "#1d1d21"
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
                            color: "#17171a"
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 3
                                Text { text: inspectorController.referenceSummary; color: "#bdbdbd"; font.pixelSize: 11 }
                                Text {
                                    Layout.fillWidth: true
                                    visible: inspectorController.nativeWarning
                                    text: inspectorController.nativeWarning
                                    color: "#e3b74a"
                                    font.pixelSize: 9
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            color: "#1d1d21"
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
                            reuseItems: true
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: AppScrollBar {}
                            model: inspectorController.referenceRows
                            delegate: Rectangle {
                                id: referenceRow
                                required property var modelData
                                required property int index
                                width: ListView.view.width
                                height: 36
                                color: index % 2 ? "#1b1b1f" : "#1d1d21"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    Text {
                                        text: referenceRow.modelData.action
                                        color: referenceRow.modelData.action === "Update" ? "#70b18f" : "#e3b74a"
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
