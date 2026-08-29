import QtCore
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1160
    height: 800
    minimumWidth: 900
    minimumHeight: 640
    visible: true
    title: "Quest APK Renamer"
    color: "#111113"

    property color textPrimary: "#eeeeee"
    property color textSecondary: "#939393"
    property color line: "#2f2f36"
    property color panel: "#1a1a1e"
    property color panelRaised: "#1f1f24"
    property color accent: "#4b90cc"
    readonly property int pageMargin: 30
    property int pageIndex: 0
    property int requestedPage: 0

    // Remember window placement and the last open page between sessions.
    Settings {
        id: windowState
        category: "MainWindow"
        property alias x: window.x
        property alias y: window.y
        property alias width: window.width
        property alias height: window.height
        property alias page: window.pageIndex
    }

    function toneColor(tone, fallback) {
        if (tone === "error") return "#e5706a"
        if (tone === "warning") return "#e3b74a"
        if (tone === "success") return "#70b18f"
        if (tone === "active") return window.accent
        return fallback === undefined ? "#7c7c7c" : fallback
    }

    Shortcut { sequence: "Ctrl+1"; onActivated: window.showPage(0) }
    Shortcut { sequence: "Ctrl+2"; onActivated: window.showPage(1) }
    Shortcut { sequence: "Ctrl+3"; onActivated: window.showPage(2) }
    Shortcut { sequence: "Ctrl+4"; onActivated: window.showPage(3) }
    Shortcut { sequence: "Ctrl+5"; onActivated: window.showPage(4) }
    Shortcut { sequence: "Ctrl+L"; onActivated: logWindow.openWindow() }
    Shortcut { sequences: [StandardKey.Quit, "Ctrl+Q"]; onActivated: window.close() }

    // Quitting mid-transfer would leave a half-copied folder or a half-installed
    // game; ask first while any worker is running.
    onClosing: close => {
        if (appController.isBusy || bulkController.isBusy) {
            close.accepted = false
            quitDialog.open()
        }
    }
    Shortcut {
        sequence: "Ctrl+O"
        onActivated: {
            if (appController.isBusy)
                return
            window.showPage(0)
            fileDialogController.chooseFolder(
                "game",
                "Choose a Quest game folder",
                appController.lastSourceFolder
            )
        }
    }
    Shortcut {
        sequence: "Ctrl+B"
        onActivated: {
            if (window.pageIndex === 0 && appController.canBuild)
                appController.requestBuild()
        }
    }
    Shortcut {
        sequence: "Ctrl+R"
        onActivated: appController.refreshDevice()
    }

    function showPage(index) {
        if (index === pageIndex)
            return
        requestedPage = index
        pageChange.restart()
    }

    SequentialAnimation {
        id: pageChange
        NumberAnimation {
            target: pageHost
            property: "opacity"
            to: 0
            duration: 75
            easing.type: Easing.InQuad
        }
        ScriptAction { script: window.pageIndex = window.requestedPage }
        NumberAnimation {
            target: pageHost
            property: "opacity"
            to: 1
            duration: 140
            easing.type: Easing.OutCubic
        }
    }

    Connections {
        target: fileDialogController
        function onFolderSelected(purpose, url) {
            if (purpose === "game")
                appController.chooseFolder(url)
            else if (purpose === "output")
                appController.chooseOutputParent(url)
            else if (purpose === "install")
                appController.installFinishedFolder(url)
            else if (purpose === "libraryUpdate") {
                appController.chooseLibraryUpdate(url)
                window.showPage(0)
            }
            else if (purpose === "signingBackup")
                appController.backupSigningKey(url)
            else if (purpose === "defaultKeyBackup")
                appController.setDefaultKeyBackupFolder(url)
            else if (purpose === "signingRestore")
                appController.restoreSigningKey(url)
            else if (purpose === "bulkFolder")
                bulkController.addFolder(url)
            else if (purpose === "bulkScan")
                bulkController.scanParent(url)
            else if (purpose === "cleanupOutput")
                appController.requestOldOutputCleanup(url)
        }
        function onFilesSelected(purpose, urls) {
            if (purpose === "bulkApks")
                bulkController.addApks(urls)
        }
        function onFileSelected(purpose, url) {
            if (purpose === "libraryUpdate") {
                appController.chooseLibraryUpdate(url)
                window.showPage(0)
            }
            else if (purpose === "libraryImport")
                libraryController.prepareImport(url)
        }
        function onSelectionCancelled(purpose) {
            if (purpose === "libraryUpdate")
                appController.cancelLibraryUpdateSelection()
        }
        function onDialogFailed(detail) {
            pickerFailureDialog.bodyText = detail
            pickerFailureDialog.open()
            appController.recordActivity("File picker failed: " + detail)
        }
        function onSaveSelected(purpose, url) {
            if (purpose === "activityLog")
                appController.exportLog(url)
            else if (purpose === "libraryExportSelected")
                libraryController.exportSelected(url)
            else if (purpose === "libraryExportAll")
                libraryController.exportAll(url)
        }
    }

    DecisionDialog {
        id: quitDialog
        heading: "Quit while work is running?"
        bodyText: "A build, install, or tool download is still running. Quitting now can leave a half-finished folder or a half-installed game on the Quest."
        primaryText: "Keep working"
        secondaryText: "Quit anyway"
        onSecondaryChosen: Qt.quit()
    }

    DecisionDialog {
        id: pickerFailureDialog
        heading: "File picker unavailable"
        bodyText: ""
        primaryText: "Close"
        secondaryText: "Open logs"
        onSecondaryChosen: logWindow.openWindow()
    }

    DecisionDialog {
        id: libraryImportDialog
        heading: "Import saved identities?"
        bodyText: ""
        primaryText: "Import"
        secondaryText: "Cancel"
        onPrimaryChosen: libraryController.confirmImport()
        onSecondaryChosen: libraryController.cancelImport()
        onDismissed: libraryController.cancelImport()
    }

    DecisionDialog {
        id: libraryDeleteDialog
        heading: "Remove this saved identity?"
        bodyText: "This removes the game from the key vault, so it will no longer be matched automatically. Private key files are kept on disk."
        primaryText: "Remove identity"
        secondaryText: "Cancel"
        destructive: true
        onPrimaryChosen: libraryController.deleteSelected()
    }

    Connections {
        target: libraryController
        function onImportConfirmationRequested(summary) {
            libraryImportDialog.bodyText = summary
            libraryImportDialog.open()
        }
    }

    DecisionDialog {
        id: partialBuildDialog
        property string partialPath: appController.partialOutputFolder
        heading: "Remove the partial build?"
        bodyText: "The previous build stopped after creating temporary output. Your source folder is unchanged.\n\n" + partialPath
        primaryText: "Remove partial files"
        secondaryText: "Keep them"
        tertiaryText: "Open folder"
        destructive: true
        onPrimaryChosen: appController.discardPartialBuild()
        onSecondaryChosen: appController.keepPartialBuild()
        onTertiaryChosen: appController.openPartialBuild()
        onDismissed: appController.keepPartialBuild()
    }

    DecisionDialog {
        id: signingBackupReminderDialog
        heading: "Back up your signing key"
        bodyText: "This key is required to update renamed apps later. Save one private backup folder now, or do it from Settings when convenient."
        primaryText: "Choose backup location"
        secondaryText: "Later"
        onPrimaryChosen: fileDialogController.chooseFolder(
            "signingBackup",
            "Choose where to save the private signing-key backup",
            appController.folderPath
        )
    }

    DecisionDialog {
        id: signingBackupCompletedDialog
        property string backupPath: ""
        heading: "Signing key backed up"
        bodyText: "Your signing key is still saved automatically with its Library entry. A separate backup was also created here:\n\n" + backupPath
        primaryText: "Done"
        secondaryText: "Open backup"
        onSecondaryChosen: appController.openKeyBackupFolder(backupPath)
    }

    DecisionDialog {
        id: outputConflictDialog
        property string existingPath: ""
        property string alternativePath: ""
        heading: "That save folder already exists"
        bodyText: "Choose a different numbered folder, replace the existing folder, or cancel.\n\nExisting: " + existingPath + "\n\nNumbered copy: " + alternativePath
        primaryText: "Replace existing"
        secondaryText: "Cancel"
        tertiaryText: "Use numbered copy"
        destructive: true
        onPrimaryChosen: appController.replaceExistingOutput()
        onSecondaryChosen: appController.cancelOutputConflict()
        onTertiaryChosen: appController.useNumberedOutput()
        onDismissed: appController.cancelOutputConflict()
    }

    DecisionDialog {
        id: signingRestoreConfirmationDialog
        heading: "Replace the current signing identity?"
        bodyText: "The selected backup will become the identity used for future builds. The current identity will be preserved in a recovery folder."
        primaryText: "Restore backup"
        secondaryText: "Cancel"
        destructive: true
        onPrimaryChosen: appController.confirmSigningKeyRestore()
        onSecondaryChosen: appController.cancelSigningKeyRestore()
        onDismissed: appController.cancelSigningKeyRestore()
    }

    DecisionDialog {
        id: packageConflictDialog
        property string packageName: ""
        heading: "This app is already installed"
        bodyText: packageName + " is already on the Quest. Updating keeps its existing app data and synchronizes the APK and OBB files.\n\nTo install a separate copy, build it with a different app ID."
        primaryText: "Update"
        secondaryText: "Cancel"
        onPrimaryChosen: appController.continuePackageInstall()
        onSecondaryChosen: appController.cancelPackageInstall()
        onDismissed: appController.cancelPackageInstall()
    }

    DecisionDialog {
        id: uninstallDialog
        property string packageName: ""
        property string reason: ""
        heading: "Replace the app on the Quest?"
        bodyText: reason + "\n\nUninstalling " + packageName + " removes its app data and save "
                  + "files from the headset. The finished folder is then installed in its place."
        primaryText: "Uninstall and install"
        secondaryText: "Keep existing app"
        destructive: true
        onPrimaryChosen: appController.confirmUninstallAndReinstall()
        onSecondaryChosen: appController.cancelUninstallAndReinstall()
        onDismissed: appController.cancelUninstallAndReinstall()
    }

    DecisionDialog {
        id: replaceSourceDialog
        heading: "Replace the source after building?"
        bodyText: "The complete renamed bundle is built and verified in a separate folder first. It then takes the original folder path, and the unedited folder is moved to Trash."
        primaryText: "Enable replacement"
        secondaryText: "Cancel"
        destructive: true
        onPrimaryChosen: appController.confirmReplaceSource()
        onSecondaryChosen: appController.cancelReplaceSource()
        onDismissed: appController.cancelReplaceSource()
    }

    DecisionDialog {
        id: oldOutputCleanupDialog
        property string outputPath: ""
        property string outputSize: ""
        property string packageName: ""
        heading: "Move this old output to Trash?"
        bodyText: outputPath + "\n\nPackage: " + packageName + "\nSize: " + outputSize
                  + "\n\nOnly a folder with a valid Quest APK Renamer build report is accepted. It can be restored from your desktop Trash."
        primaryText: "Move to Trash"
        secondaryText: "Cancel"
        destructive: true
        onPrimaryChosen: appController.confirmOldOutputCleanup()
        onSecondaryChosen: appController.cancelOldOutputCleanup()
        onDismissed: appController.cancelOldOutputCleanup()
    }

    DecisionDialog {
        id: bulkConfirmationDialog
        property string operation: ""
        heading: "Start bulk operation?"
        bodyText: ""
        primaryText: operation === "build" ? "Build queue" : "Install queue"
        secondaryText: "Cancel"
        destructive: operation === "build" && bulkController.replaceSources
        onPrimaryChosen: bulkController.confirmOperation()
        onSecondaryChosen: bulkController.cancelConfirmation()
        onDismissed: bulkController.cancelConfirmation()
    }

    Connections {
        target: appController
        function onPartialOutputChanged() {
            if (appController.partialOutputFolder)
                partialBuildDialog.open()
        }
        function onSigningBackupReminderRequested() {
            signingBackupReminderDialog.open()
        }
        function onSigningBackupCompletedRequested(path) {
            signingBackupCompletedDialog.backupPath = path
            signingBackupCompletedDialog.open()
        }
        function onOutputConflictRequested(existingPath, alternativePath) {
            outputConflictDialog.existingPath = existingPath
            outputConflictDialog.alternativePath = alternativePath
            outputConflictDialog.open()
        }
        function onSigningRestoreConfirmationRequested(path) {
            signingRestoreConfirmationDialog.open()
        }
        function onPackageConflictRequested(packageName) {
            packageConflictDialog.packageName = packageName
            packageConflictDialog.open()
        }
        function onUninstallSuggested(packageName, reason) {
            uninstallDialog.packageName = packageName
            uninstallDialog.reason = reason
            uninstallDialog.open()
        }
        function onReplaceSourceConfirmationRequested() {
            replaceSourceDialog.open()
        }
        function onOutputCleanupConfirmationRequested(path, size, packageName) {
            oldOutputCleanupDialog.outputPath = path
            oldOutputCleanupDialog.outputSize = size
            oldOutputCleanupDialog.packageName = packageName
            oldOutputCleanupDialog.open()
        }
    }

    Connections {
        target: bulkController
        function onConfirmationRequested(mode, title, body) {
            bulkConfirmationDialog.operation = mode
            bulkConfirmationDialog.heading = title
            bulkConfirmationDialog.bodyText = body
            bulkConfirmationDialog.open()
        }
    }

    LogWindow { id: logWindow }

    Component.onCompleted: {
        if (appController.partialOutputFolder)
            partialBuildDialog.open()
    }

    header: Rectangle {
        implicitHeight: 50
        color: "#161619"

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: window.line
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 20
            spacing: 10

            Rectangle {
                id: deviceChip
                implicitWidth: deviceContent.implicitWidth + 22
                implicitHeight: 32
                radius: 4
                color: deviceMouse.containsMouse || deviceMenu.visible ? "#26262c" : "#1f1f24"
                border.width: 1
                border.color: deviceMenu.visible ? "#52525d"
                            : appController.deviceTone === "error" ? "#65393a"
                            : appController.deviceTone === "warning" ? "#5a4f1c"
                            : appController.deviceTone === "success" ? "#3d6654"
                            : "#3a3a43"
                Row {
                    id: deviceContent
                    anchors.centerIn: parent
                    spacing: 8
                    Rectangle {
                        width: 8
                        height: 8
                        radius: 4
                        anchors.verticalCenter: parent.verticalCenter
                        color: window.toneColor(appController.deviceTone, "#7d7d7d")
                    }
                    Text {
                        text: appController.deviceLabel
                        color: "#d0d0d0"
                        font.pixelSize: 12
                        font.weight: Font.Medium
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    IconImage {
                        width: 12
                        height: 12
                        sourceSize.width: 12
                        sourceSize.height: 12
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.verticalCenterOffset: 1
                        source: Qt.resolvedUrl("../assets/icon-chevron-down.svg")
                        color: deviceMouse.containsMouse || deviceMenu.visible ? "#cfcfcf" : "#8a8a8a"
                        rotation: deviceMenu.visible ? 180 : 0
                        Behavior on rotation { NumberAnimation { duration: 120 } }
                    }
                }
                MouseArea {
                    id: deviceMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: deviceMenu.visible ? deviceMenu.close() : deviceMenu.open()
                }
                Accessible.role: Accessible.Button
                Accessible.name: "Quest status: " + appController.deviceLabel + ". Open device panel."
                ToolTip {
                    visible: deviceMouse.containsMouse && !deviceMenu.visible
                    delay: 600
                    text: "Attached and saved wireless Quests"
                }

                Popup {
                    id: deviceMenu
                    objectName: "deviceMenu"
                    parent: deviceChip
                    x: 0
                    y: deviceChip.height + 6
                    width: 372
                    padding: 0
                    modal: false
                    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                    enter: Transition {
                        ParallelAnimation {
                            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 110 }
                            NumberAnimation { property: "y"; from: deviceChip.height; to: deviceChip.height + 6; duration: 120; easing.type: Easing.OutCubic }
                        }
                    }
                    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 80 } }
                    background: Rectangle {
                        color: "#1e1e22"
                        border.width: 1
                        border.color: "#40404a"
                        radius: 6
                    }

                    contentItem: ColumnLayout {
                        spacing: 0

                        // Status block
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.margins: 14
                            Layout.bottomMargin: 12
                            spacing: 12
                            Rectangle {
                                Layout.preferredWidth: 34
                                Layout.preferredHeight: 34
                                radius: 17
                                color: appController.deviceTone === "success" ? "#25382f"
                                     : appController.deviceTone === "warning" ? "#312c12"
                                     : appController.deviceTone === "error" ? "#351f1f"
                                     : "#29292f"
                                IconImage {
                                    anchors.centerIn: parent
                                    width: 16
                                    height: 16
                                    sourceSize.width: 16
                                    sourceSize.height: 16
                                    source: Qt.resolvedUrl(appController.isWirelessDevice
                                                           ? "../assets/icon-wifi.svg"
                                                           : "../assets/icon-usb.svg")
                                    color: window.toneColor(appController.deviceTone, "#8a8a8a")
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    Layout.fillWidth: true
                                    text: appController.deviceLabel
                                    color: "#f0f0f0"
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: appController.deviceDetail
                                    color: window.textSecondary
                                    font.pixelSize: 11
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        // Attached devices (only when the user has to choose)
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#32323a"; visible: attachedColumn.visible }
                        ColumnLayout {
                            id: attachedColumn
                            visible: appController.deviceChoices.length > 1
                            Layout.fillWidth: true
                            Layout.margins: 8
                            spacing: 2
                            SectionLabel {
                                text: "ATTACHED DEVICES"
                                Layout.leftMargin: 6
                                Layout.topMargin: 4
                                Layout.bottomMargin: 4
                            }
                            Repeater {
                                model: appController.deviceChoices
                                delegate: Rectangle {
                                    id: attachedRow
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 40
                                    radius: 4
                                    color: attachedHover.hovered ? "#28282e" : "transparent"
                                    HoverHandler { id: attachedHover }
                                    TapHandler { onTapped: { appController.selectDevice(attachedRow.modelData.serial); deviceMenu.close() } }
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 6
                                        spacing: 10
                                        IconImage {
                                            width: 15; height: 15
                                            sourceSize.width: 15; sourceSize.height: 15
                                            source: Qt.resolvedUrl(attachedRow.modelData.serial.indexOf(":") >= 0
                                                                   ? "../assets/icon-wifi.svg" : "../assets/icon-usb.svg")
                                            color: "#a9a9a9"
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: attachedRow.modelData.label
                                            color: "#e6e6e6"
                                            font.pixelSize: 12
                                            elide: Text.ElideMiddle
                                        }
                                        AppButton {
                                            text: "Use"
                                            quiet: true
                                            implicitHeight: 26
                                            leftPadding: 10; rightPadding: 10
                                            font.pixelSize: 11
                                            onClicked: { appController.selectDevice(attachedRow.modelData.serial); deviceMenu.close() }
                                        }
                                    }
                                }
                            }
                        }

                        // Saved wireless Quests
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#32323a" }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.margins: 8
                            spacing: 2
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.leftMargin: 6
                                Layout.rightMargin: 6
                                Layout.topMargin: 4
                                Layout.bottomMargin: 4
                                SectionLabel { text: "SAVED WIRELESS QUESTS" }
                                Item { Layout.fillWidth: true }
                                Text {
                                    visible: appController.wirelessBusy
                                    text: "Working…"
                                    color: "#9a9a9a"
                                    font.pixelSize: 10
                                }
                            }
                            Text {
                                visible: appController.savedWirelessDevices.length === 0
                                Layout.fillWidth: true
                                Layout.leftMargin: 6
                                Layout.rightMargin: 6
                                Layout.bottomMargin: 6
                                text: "Nothing saved yet. Enable wireless ADB over USB once, or add an address, and the headset is remembered here."
                                color: "#8f8f8f"
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                            Repeater {
                                model: appController.savedWirelessDevices
                                delegate: Rectangle {
                                    id: savedRowItem
                                    required property var modelData
                                    readonly property bool isCurrent: appController.isWirelessDevice
                                                                       && appController.deviceTone === "success"
                                                                       && appController.deviceLabel.length > 0
                                                                       && appController.currentSerial === modelData.address
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 46
                                    radius: 4
                                    color: savedHover.hovered && !isCurrent ? "#28282e" : "transparent"
                                    HoverHandler { id: savedHover }
                                    TapHandler {
                                        enabled: !savedRowItem.isCurrent && !appController.wirelessBusy
                                        onTapped: appController.connectWireless(savedRowItem.modelData.address)
                                    }
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 6
                                        spacing: 10
                                        IconImage {
                                            width: 15; height: 15
                                            sourceSize.width: 15; sourceSize.height: 15
                                            source: Qt.resolvedUrl("../assets/icon-wifi.svg")
                                            color: savedRowItem.isCurrent ? "#70b18f" : "#a9a9a9"
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 1
                                            Text {
                                                Layout.fillWidth: true
                                                text: savedRowItem.modelData.label || "Quest"
                                                color: "#e6e6e6"
                                                font.pixelSize: 12
                                                font.weight: Font.Medium
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: savedRowItem.modelData.address
                                                color: "#8d8d8d"
                                                font.pixelSize: 10
                                                elide: Text.ElideMiddle
                                            }
                                        }
                                        Text {
                                            visible: savedRowItem.isCurrent
                                            text: "Connected"
                                            color: "#70b18f"
                                            font.pixelSize: 11
                                            font.weight: Font.Medium
                                            rightPadding: 6
                                        }
                                        AppButton {
                                            visible: !savedRowItem.isCurrent
                                            text: "Connect"
                                            quiet: true
                                            implicitHeight: 26
                                            leftPadding: 10; rightPadding: 10
                                            font.pixelSize: 11
                                            enabled: !appController.wirelessBusy
                                            onClicked: appController.connectWireless(savedRowItem.modelData.address)
                                        }
                                    }
                                }
                            }
                        }

                        // Actions
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#32323a" }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.margins: 12
                            spacing: 8
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                AppButton {
                                    Layout.fillWidth: true
                                    visible: !appController.isWirelessDevice
                                    text: "Enable over USB"
                                    implicitHeight: 30
                                    font.pixelSize: 11
                                    enabled: appController.deviceTone === "success" && !appController.wirelessBusy
                                    tip: "Switch the USB-connected headset to wireless ADB and remember it"
                                    onClicked: appController.enableWirelessOverUsb()
                                }
                                AppButton {
                                    Layout.fillWidth: true
                                    visible: appController.isWirelessDevice
                                    text: "Disconnect"
                                    implicitHeight: 30
                                    font.pixelSize: 11
                                    enabled: !appController.wirelessBusy
                                    onClicked: appController.disconnectWireless()
                                }
                                AppButton {
                                    Layout.fillWidth: true
                                    text: "Add address…"
                                    implicitHeight: 30
                                    font.pixelSize: 11
                                    onClicked: {
                                        deviceMenu.close()
                                        window.showPage(4)
                                        wirelessField.forceActiveFocus()
                                    }
                                }
                            }
                            Text {
                                visible: appController.wirelessStatus.length > 0
                                Layout.fillWidth: true
                                text: appController.wirelessStatus
                                color: appController.wirelessTone === "error" ? "#e88780"
                                     : appController.wirelessTone === "success" ? "#78b894"
                                     : appController.wirelessTone === "warning" ? "#e3b74a"
                                     : window.textSecondary
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
            // Small refresh control beside the chip; the chip itself opens the device menu.
            AbstractButton {
                id: refreshButton
                implicitWidth: 28
                implicitHeight: 28
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                Accessible.name: "Refresh Quest status"
                ToolTip.visible: hovered
                ToolTip.delay: 450
                ToolTip.text: "Refresh Quest status (Ctrl+R)"
                onClicked: appController.refreshDevice()
                background: Rectangle {
                    radius: 3
                    color: refreshButton.down ? "#29292f" : refreshButton.hovered ? "#24242a" : "transparent"
                }
                contentItem: Item {
                    IconImage {
                        anchors.centerIn: parent
                        width: 14
                        height: 14
                        sourceSize.width: 14
                        sourceSize.height: 14
                        source: Qt.resolvedUrl("../assets/icon-refresh.svg")
                        color: refreshButton.hovered ? "#d7d7d7" : "#8f8f8f"
                        RotationAnimation on rotation {
                            running: appController.deviceTone === "neutral"
                                     && appController.deviceLabel.indexOf("Checking") === 0
                            loops: Animation.Infinite
                            from: 0
                            to: 360
                            duration: 1100
                        }
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "v" + appVersion
                color: "#777777"
                font.pixelSize: 11
                Layout.leftMargin: 4
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 174
            Layout.fillHeight: true
            color: "#131315"

            Rectangle {
                anchors.right: parent.right
                width: 1
                height: parent.height
                color: window.line
            }

            ColumnLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 0

                Text {
                    text: "WORKSPACE"
                    color: "#707070"
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.1
                    Layout.leftMargin: 10
                    Layout.topMargin: 7
                    Layout.bottomMargin: 8
                }
                NavItem {
                    Layout.fillWidth: true
                    label: "Dashboard"
                    iconSource: Qt.resolvedUrl("../assets/nav-dashboard.svg")
                    selected: window.pageIndex === 0
                    onClicked: window.showPage(0)
                }
                NavItem {
                    Layout.fillWidth: true
                    label: "Library"
                    iconSource: Qt.resolvedUrl("../assets/nav-library.svg")
                    selected: window.pageIndex === 1
                    onClicked: window.showPage(1)
                }
                NavItem {
                    Layout.fillWidth: true
                    label: "Bulk queue"
                    iconSource: Qt.resolvedUrl("../assets/nav-bulk.svg")
                    selected: window.pageIndex === 2
                    onClicked: window.showPage(2)
                }
                NavItem {
                    Layout.fillWidth: true
                    label: "APK Inspector"
                    iconSource: Qt.resolvedUrl("../assets/nav-inspector.svg")
                    selected: window.pageIndex === 3
                    onClicked: window.showPage(3)
                }
                NavItem {
                    Layout.fillWidth: true
                    label: "Settings"
                    iconSource: Qt.resolvedUrl("../assets/nav-settings.svg")
                    selected: window.pageIndex === 4
                    onClicked: window.showPage(4)
                }
            }

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                anchors.bottomMargin: 20

                AppButton {
                    width: parent.width
                    text: "Open logs"
                    quiet: true
                    onClicked: logWindow.openWindow()
                }
            }
        }

        Item {
            id: pageHost
            Layout.fillWidth: true
            Layout.fillHeight: true

            Rectangle {
                id: updateBanner
                visible: updateController.bannerVisible
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 30
                anchors.rightMargin: 30
                anchors.topMargin: 12
                height: 42
                radius: 3
                color: "#202b25"
                border.width: 1
                border.color: "#3d5c49"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 13
                    anchors.rightMargin: 6
                    spacing: 8
                    Rectangle {
                        Layout.preferredWidth: 7
                        Layout.preferredHeight: 7
                        radius: 4
                        color: "#70b18f"
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Update available: " + updateController.latestVersion
                        color: "#cfe2d6"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                        elide: Text.ElideRight
                    }
                    AppButton { text: "View release"; quiet: true; onClicked: updateController.openRelease() }
                    AppButton { text: "Dismiss"; quiet: true; onClicked: updateController.dismiss() }
                }
            }

            StackLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: updateBanner.visible ? updateBanner.bottom : parent.top
                anchors.bottom: parent.bottom
                anchors.topMargin: updateBanner.visible ? 6 : 0
                currentIndex: window.pageIndex

                // Dashboard
                Item {
                    PageScroller {
                        id: dashboardScroll
                        anchors.fill: parent
                        page: dashboardColumn

                        ColumnLayout {
                            id: dashboardColumn
                            x: window.pageMargin
                            y: dashboardScroll.topInset
                            width: dashboardScroll.width - 2 * window.pageMargin
                            spacing: 16

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Item {
                                    Layout.fillWidth: true
                                }
                                AppButton {
                                    visible: appController.hasBundle && !appController.isBusy
                                    text: "Clear"
                                    quiet: true
                                    tip: "Forget the selected source and start over"
                                    onClicked: appController.startOver()
                                }
                                AppButton {
                                    text: "Install built game"
                                    enabled: appController.canInstallBuilt
                                    tip: "Install the APK and OBB files produced by the last build"
                                    onClicked: appController.installBuiltFolder()
                                }
                                AppButton {
                                    text: appController.installActionLabel
                                    enabled: appController.canInstallFolder
                                    tip: "Choose a previously built game folder and install it"
                                    onClicked: fileDialogController.chooseFolder(
                                        "install",
                                        "Choose a finished game folder",
                                        appController.outputFolder || appController.lastOutputParent
                                    )
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: sourceColumn.implicitHeight + 32
                                color: sourceDrop.containsDrag ? "#222227" : window.panel
                                border.color: sourceDrop.containsDrag ? window.accent : window.line
                                opacity: appController.isBusy ? 0.75 : 1
                                Behavior on color { ColorAnimation { duration: 100 } }

                                DropArea {
                                    id: sourceDrop
                                    anchors.fill: parent
                                    enabled: !appController.isBusy
                                    onDropped: function(drop) {
                                        if (drop.urls.length > 0)
                                            appController.chooseFolder(drop.urls[0])
                                    }
                                }

                                ColumnLayout {
                                    id: sourceColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 16
                                    spacing: 7
                                    SectionLabel { text: "SOURCE" }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        TextField {
                                            id: sourceField
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 38
                                            enabled: !appController.isBusy
                                            text: appController.folderPath
                                            placeholderText: "Game folder or APK file"
                                            color: window.textPrimary
                                            font.pixelSize: 12
                                            selectByMouse: true
                                            leftPadding: 11
                                            rightPadding: 11
                                            onEditingFinished: {
                                                if (text && text !== appController.folderPath)
                                                    appController.chooseFolderPath(text)
                                            }
                                            background: Rectangle {
                                                radius: 3
                                                color: "#131316"
                                                border.width: 1
                                                border.color: sourceField.activeFocus ? window.accent : "#3e3e48"
                                            }
                                        }
                                        AppButton {
                                            visible: appController.hasBundle
                                            text: "Open"
                                            quiet: true
                                            tip: "Open the source folder in your file manager"
                                            onClicked: appController.openSourceFolder()
                                        }
                                        AppButton {
                                            text: "Browse…"
                                            primary: !appController.hasBundle
                                            enabled: !appController.isBusy
                                            tip: "Choose a game folder (Ctrl+O)"
                                            onClicked: fileDialogController.chooseFolder(
                                                "game",
                                                "Choose a Quest game folder",
                                                appController.folderPath || appController.lastSourceFolder
                                            )
                                        }
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 16
                                        Text {
                                            id: sourceSummary
                                            anchors.left: parent.left
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: Math.min(
                                                       implicitWidth,
                                                       parent.width - (ofpSourceStatus.visible ? 24 : 0)
                                                   )
                                            text: appController.hasBundle
                                                  ? appController.apkName + "  •  " + appController.obbSummary + "  •  " + appController.bundleSize
                                                    + (appController.versionSummary ? "  •  " + appController.versionSummary : "")
                                                    + (appController.libraryMatch ? "  •  " + appController.libraryMatch : "")
                                                  : "Paste a path, browse, or drop one APK or game folder here."
                                            color: appController.hasBundle ? window.textSecondary : "#8a8a8a"
                                            font.pixelSize: 10
                                            elide: Text.ElideRight
                                            ToolTip.visible: truncated && sourceSummaryHover.hovered
                                            ToolTip.text: text
                                            ToolTip.delay: 400
                                            HoverHandler { id: sourceSummaryHover }
                                        }
                                        Text {
                                            id: ofpSourceStatus
                                            visible: appController.hasBundle
                                            anchors.left: sourceSummary.right
                                            anchors.leftMargin: 7
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: appController.isAnalyzing ? "…"
                                                  : appController.olderFirmwareSupported ? "✓"
                                                  : "×"
                                            color: appController.olderFirmwareSupported ? "#70b18f"
                                                   : "#686868"
                                            font.pixelSize: 12
                                            font.weight: Font.DemiBold
                                            Accessible.name: appController.olderFirmwareEligibility
                                            ToolTip.visible: ofpStatusMouse.containsMouse
                                            ToolTip.text: appController.olderFirmwareEligibility
                                            ToolTip.delay: 300
                                            MouseArea {
                                                id: ofpStatusMouse
                                                anchors.fill: parent
                                                anchors.margins: -5
                                                hoverEnabled: true
                                                acceptedButtons: Qt.NoButton
                                            }
                                        }
                                    }
                                }

                            }

                            RowLayout {
                                id: identityRow
                                Layout.fillWidth: true
                                spacing: 14
                                // Both panels share the taller of the two content heights.
                                readonly property int panelHeight: Math.max(
                                    identityColumn.implicitHeight + 36,
                                    outputColumn.implicitHeight + 28,
                                    250
                                )

                                Panel {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: identityRow.panelHeight

                                    ColumnLayout {
                                        id: identityColumn
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 18
                                        spacing: 8
                                        SectionLabel { text: "APP IDENTITY" }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            Text {
                                                Layout.fillWidth: true
                                                text: appController.hasBundle ? appController.sourcePackage : "Current package appears here"
                                                color: appController.hasBundle ? "#b5b5b5" : "#8a8a8a"
                                                font.pixelSize: 11
                                                elide: Text.ElideMiddle
                                            }
                                            AppButton {
                                                visible: appController.hasBundle
                                                text: "Copy"
                                                quiet: true
                                                implicitHeight: 22
                                                leftPadding: 8
                                                rightPadding: 8
                                                font.pixelSize: 10
                                                tip: "Copy the original package ID"
                                                onClicked: appController.copyText(appController.sourcePackage)
                                            }
                                        }
                                        TextField {
                                            id: packageField
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 42
                                            enabled: appController.hasBundle
                                                     && !appController.isBuilding
                                                     && !appController.isDirectLibraryUpdate
                                            text: appController.packageId
                                            placeholderText: "com.dev.studio.game"
                                            color: window.textPrimary
                                            placeholderTextColor: "#7b8896"
                                            font.pixelSize: 14
                                            selectByMouse: true
                                            leftPadding: 12
                                            rightPadding: 12
                                            // Debounce validation so preflight does not run per keystroke.
                                            onTextEdited: packageDebounce.restart()
                                            onEditingFinished: {
                                                packageDebounce.stop()
                                                if (text !== appController.packageId)
                                                    appController.setPackageId(text)
                                            }
                                            Timer {
                                                id: packageDebounce
                                                interval: 180
                                                repeat: false
                                                onTriggered: appController.setPackageId(packageField.text)
                                            }
                                            background: Rectangle {
                                                radius: 6
                                                color: "#131316"
                                                border.width: 1
                                                border.color: packageField.activeFocus ? window.accent
                                                              : appController.packageError && appController.hasBundle ? "#7d3d3b"
                                                              : "#3e3e48"
                                            }
                                        }
                                        RowLayout {
                                            spacing: 6
                                            readonly property bool tagsEnabled: appController.hasBundle
                                                                                && !appController.isBuilding
                                                                                && !appController.isDirectLibraryUpdate
                                            AppButton { text: ".mr"; enabled: parent.tagsEnabled; tip: "Append .mr to the original package ID"; onClicked: appController.applyTag("mr") }
                                            AppButton { text: ".dev"; enabled: parent.tagsEnabled; tip: "Append .dev to the original package ID"; onClicked: appController.applyTag("dev") }
                                            AppButton { text: ".test"; enabled: parent.tagsEnabled; tip: "Append .test to the original package ID"; onClicked: appController.applyTag("test") }
                                            AppButton { text: ".qa"; enabled: parent.tagsEnabled; tip: "Append .qa to the original package ID"; onClicked: appController.applyTag("qa") }
                                            Item { Layout.fillWidth: true }
                                        }
                                        RowLayout {
                                            visible: appController.settings.changeDisplayName
                                            Layout.fillWidth: true
                                            spacing: 8
                                            Text {
                                                text: "Display name"
                                                color: "#9a9a9a"
                                                font.pixelSize: 11
                                            }
                                            TextField {
                                                id: labelField
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 30
                                                enabled: packageField.enabled
                                                text: appController.appLabel
                                                placeholderText: appController.displayNamePreview
                                                onVisibleChanged: if (!visible && appController.appLabel) appController.setAppLabel("")
                                                color: window.textPrimary
                                                placeholderTextColor: "#7b8896"
                                                font.pixelSize: 12
                                                selectByMouse: true
                                                leftPadding: 10
                                                rightPadding: 10
                                                onEditingFinished: {
                                                    if (text !== appController.appLabel)
                                                        appController.setAppLabel(text)
                                                }
                                                ToolTip.visible: hovered
                                                ToolTip.delay: 600
                                                ToolTip.text: "Experimental: optional launcher name for the renamed copy. Changing it may cause errors in some apps. Leave empty to keep the original (the Settings suffix still applies)."
                                                background: Rectangle {
                                                    radius: 6
                                                    color: "#131316"
                                                    border.width: 1
                                                    border.color: labelField.activeFocus ? window.accent : "#3e3e48"
                                                }
                                            }
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            readonly property bool labelChange: appController.hasBundle
                                                                                && !appController.packageError
                                                                                && appController.settings.changeDisplayName
                                                                                && (appController.appLabel !== "" || appController.settings.labelSuffix !== "")
                                            text: appController.hasBundle
                                                  ? (appController.packageError
                                                     || (labelChange ? "Display name will change — experimental, may cause errors in some apps."
                                                                     : "Java classes and in-game text stay unchanged."))
                                                  : "A safe suggestion is generated automatically."
                                            color: appController.packageError && appController.hasBundle ? "#e88780"
                                                   : labelChange ? "#e3b74a" : "#808080"
                                            font.pixelSize: 10
                                            elide: Text.ElideRight
                                        }
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 1
                                            color: "#2f2f36"
                                        }
                                        SectionLabel { text: "SIGNING LINEAGE" }
                                        Text {
                                            Layout.fillWidth: true
                                            text: appController.signerLineage
                                            color: appController.hasBundle ? "#a9a9a9" : "#696969"
                                            font.pixelSize: 10
                                            elide: Text.ElideMiddle
                                            ToolTip.visible: lineageMouse.containsMouse && truncated
                                            ToolTip.text: text
                                            MouseArea {
                                                id: lineageMouse
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                acceptedButtons: Qt.NoButton
                                            }
                                        }
                                    }
                                }

                                Panel {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: identityRow.panelHeight

                                    ColumnLayout {
                                        id: outputColumn
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 14
                                        spacing: 5
                                        SectionLabel {
                                            text: appController.isDirectLibraryUpdate
                                                  ? "QUEST UPDATE" : "OUTPUT"
                                        }
                                        Text {
                                            text: appController.isDirectLibraryUpdate
                                                  ? "Install selected files"
                                                  : appController.settings.replaceSourceAfterBuild
                                                  ? "Source replacement path"
                                                  : "Save location"
                                            color: appController.hasBundle ? window.textPrimary : "#6f6f6f"
                                            font.pixelSize: 13
                                            font.weight: Font.Medium
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            Rectangle {
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 30
                                                radius: 3
                                                color: outputMouse.containsMouse ? "#232328" : "#1e1e22"
                                                border.width: 1
                                                border.color: outputMouse.containsMouse ? "#494954" : "#32323a"
                                                Text {
                                                    anchors.left: parent.left
                                                    anchors.right: outputChange.left
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    anchors.leftMargin: 10
                                                    anchors.rightMargin: 8
                                                    text: appController.isDirectLibraryUpdate
                                                          ? appController.deviceTitle + "  •  " + appController.packageId
                                                          : appController.hasBundle
                                                          ? appController.outputFolder
                                                          : "Select a game to choose its save location"
                                                    color: appController.hasBundle ? window.textSecondary : "#8f8f8f"
                                                    font.pixelSize: 10
                                                    elide: Text.ElideMiddle
                                                }
                                                Text {
                                                    id: outputChange
                                                    visible: !appController.isDirectLibraryUpdate
                                                    anchors.right: parent.right
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    anchors.rightMargin: 10
                                                    text: appController.settings.replaceSourceAfterBuild
                                                          ? "Source"
                                                          : "Change…"
                                                    color: appController.hasBundle ? "#b9b9b9" : "#8f8f8f"
                                                    font.pixelSize: 10
                                                    font.weight: Font.Medium
                                                }
                                                MouseArea {
                                                    id: outputMouse
                                                    anchors.fill: parent
                                                    enabled: appController.hasBundle
                                                             && !appController.isBusy
                                                             && !appController.isDirectLibraryUpdate
                                                             && !appController.settings.replaceSourceAfterBuild
                                                    hoverEnabled: true
                                                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                                    onClicked: fileDialogController.chooseFolder(
                                                        "output",
                                                        "Choose where to save the renamed folder",
                                                        appController.outputFolder || appController.lastOutputParent
                                                    )
                                                }
                                            }
                                            AppButton {
                                                visible: appController.hasBundle && !appController.isDirectLibraryUpdate
                                                text: "Open"
                                                quiet: true
                                                implicitHeight: 30
                                                leftPadding: 9
                                                rightPadding: 9
                                                font.pixelSize: 11
                                                tip: "Open the save location (its parent folder until the build exists)"
                                                onClicked: appController.openOutputFolder()
                                            }
                                            AppButton {
                                                visible: appController.hasBundle && !appController.isDirectLibraryUpdate
                                                text: "Copy"
                                                quiet: true
                                                implicitHeight: 30
                                                leftPadding: 9
                                                rightPadding: 9
                                                font.pixelSize: 11
                                                tip: "Copy the save location path"
                                                onClicked: appController.copyText(appController.outputFolder)
                                            }
                                        }
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 1
                                            color: "#2f2f36"
                                            Layout.topMargin: 1
                                            Layout.bottomMargin: 1
                                        }
                                        SettingRow {
                                            visible: !appController.isDirectLibraryUpdate
                                            Layout.fillWidth: true
                                            compact: true
                                            enabled: !appController.isBusy
                                            title: "Older firmware patch"
                                            detail: appController.olderFirmwareDetail
                                            checked: appController.settings.olderFirmwarePatch
                                            onChanged: value => appController.setSetting("older_firmware_patch", value)
                                        }
                                        SettingRow {
                                            visible: !appController.isDirectLibraryUpdate
                                            Layout.fillWidth: true
                                            compact: true
                                            enabled: !appController.isBusy
                                            title: "Replace source after build"
                                            detail: "Verify first, then replace the selected folder"
                                            checked: appController.settings.replaceSourceAfterBuild
                                            onChanged: value => appController.requestReplaceSource(value)
                                        }
                                        SettingRow {
                                            visible: !appController.isDirectLibraryUpdate
                                            Layout.fillWidth: true
                                            compact: true
                                            enabled: !appController.isBusy
                                            title: "Delete installed folder after success"
                                            detail: "Only after the APK and every OBB are verified on Quest"
                                            checked: appController.settings.deleteSourceAfterInstall
                                            onChanged: value => appController.setSetting("delete_source_after_install", value)
                                        }
                                        Text {
                                            visible: appController.isDirectLibraryUpdate
                                            Layout.fillWidth: true
                                            Layout.topMargin: 8
                                            text: "The APK is kept unchanged so Android can verify its existing signature. OBB files are synchronized from the selected folder."
                                            color: window.textSecondary
                                            font.pixelSize: 10
                                            wrapMode: Text.WordWrap
                                        }
                                        Item {
                                            visible: appController.isDirectLibraryUpdate
                                            Layout.fillHeight: true
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                id: operationPanel
                                property bool operationActive: appController.isAnalyzing
                                                               || appController.isBuilding
                                                               || appController.isInstalling
                                property real operationProgress: appController.isInstalling
                                                                 ? appController.installProgress
                                                                 : appController.isBuilding
                                                                 ? appController.buildProgress
                                                                 : appController.analysisProgress
                                property string operationDetail: appController.isInstalling
                                                                  ? "Quest install  •  " + appController.deviceTitle
                                                                  : appController.isBuilding
                                                                  ? "Build output  •  " + appController.packageId
                                                                  : "APK analysis  •  " + appController.apkName
                                Layout.fillWidth: true
                                Layout.preferredHeight: operationActive ? 82 : 54
                                radius: 3
                                color: window.panel
                                border.width: 1
                                border.color: window.line
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 15
                                    anchors.rightMargin: 8
                                    anchors.bottomMargin: operationPanel.operationActive ? 16 : 0
                                    spacing: 10
                                    Rectangle {
                                        Layout.preferredWidth: 8
                                        Layout.preferredHeight: 8
                                        radius: 4
                                        color: appController.noticeTone === "error" ? "#e5706a"
                                             : appController.noticeTone === "warning" ? "#e3b74a"
                                             : appController.noticeTone === "success" ? "#70b18f"
                                             : "#7c7c7c"
                                        Behavior on color { ColorAnimation { duration: 120 } }
                                    }
                                    BusyIndicator {
                                        visible: appController.isAnalyzing
                                                 || appController.isBuilding
                                                 || appController.isInstalling
                                        running: visible
                                        Layout.preferredWidth: 20
                                        Layout.preferredHeight: 20
                                        Accessible.name: "Operation in progress"
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            Layout.fillWidth: true
                                            text: appController.isInstalling
                                                  ? appController.installLabel
                                                  : appController.isBuilding
                                                  ? appController.buildLabel
                                                  : appController.isAnalyzing
                                                  ? appController.analysisLabel
                                                  : appController.notice
                                            color: "#c7c7c7"
                                            font.pixelSize: 11
                                            font.weight: operationPanel.operationActive
                                                         ? Font.Medium : Font.Normal
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            visible: operationPanel.operationActive
                                            text: operationPanel.operationDetail
                                            color: "#7f8a92"
                                            font.pixelSize: 9
                                            elide: Text.ElideMiddle
                                        }
                                    }
                                    Text {
                                        visible: operationPanel.operationActive
                                        text: Math.round(operationPanel.operationProgress * 100) + "%"
                                              + (appController.operationElapsed ? "  •  " + appController.operationElapsed : "")
                                        color: "#d8d8d8"
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    AppButton {
                                        visible: appController.noticeTone === "error"
                                                 && appController.hasFailureReport
                                                 && !appController.isBusy
                                        text: "Open report"
                                        quiet: true
                                        onClicked: appController.openFailureReport()
                                    }
                                    AppButton {
                                        visible: appController.noticeTone === "error"
                                                 && !appController.isBusy
                                        text: "Open logs"
                                        quiet: true
                                        onClicked: logWindow.openWindow()
                                    }
                                    AppButton {
                                        visible: appController.noticeTone === "error"
                                                 && !appController.isBusy
                                                 && appController.hasBundle
                                                 && !appController.isAnalyzing
                                        text: "Copy error"
                                        quiet: true
                                        tip: "Copy the message above to the clipboard"
                                        onClicked: appController.copyText(appController.notice)
                                    }
                                    AppButton {
                                        text: appController.isInstalling ? "Cancel install"
                                              : appController.canRetryObbs ? "Retry failed OBB transfer"
                                              : appController.buildActionLabel
                                        primary: !appController.isBuilding && !appController.isInstalling
                                        enabled: appController.isInstalling || appController.canRetryObbs
                                                 || appController.isBuilding
                                                 || appController.canBuild
                                                 || appController.hasBuildResult
                                        tip: appController.isInstalling ? "Stop after the current APK or OBB finishes"
                                             : appController.isBuilding ? "Stop the build at the next safe point"
                                             : appController.hasBuildResult ? "Open the finished folder"
                                             : "Build the renamed copy (Ctrl+B)"
                                        onClicked: {
                                            if (appController.isInstalling)
                                                appController.cancelInstall()
                                            else if (appController.canRetryObbs)
                                                appController.retryFailedObbs()
                                            else
                                                appController.requestBuild()
                                        }
                                    }
                                }
                                ThinProgress {
                                    visible: operationPanel.operationActive
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    anchors.leftMargin: 15
                                    anchors.rightMargin: 15
                                    anchors.bottomMargin: 8
                                    thickness: 8
                                    value: operationPanel.operationProgress
                                    fillColor: window.accent
                                }
                            }
                        }
                    }
                }

                // Library
                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: window.pageMargin
                        anchors.rightMargin: window.pageMargin
                        anchors.topMargin: 16
                        anchors.bottomMargin: 24
                        spacing: 12

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 42
                            spacing: 10
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 180
                                spacing: 2
                                Text {
                                    Layout.fillWidth: true
                                    text: libraryController.statusText
                                    color: window.textPrimary
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: libraryController.actionText
                                          ? libraryController.actionText
                                          : libraryController.showInstalled
                                          ? "Select an installed app, then choose the APK or complete game folder to update it."
                                          : "Signing identities are restored automatically when you choose a matching game on Dashboard."
                                    color: libraryController.actionText ? "#aebdca" : window.textSecondary
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                            }
                            Item {
                                visible: !libraryController.showInstalled
                                Layout.preferredWidth: 238
                                Layout.preferredHeight: 36
                                RowLayout {
                                    anchors.fill: parent
                                    spacing: 6
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Copy all"
                                        leftPadding: 9
                                        rightPadding: 9
                                        font.pixelSize: 11
                                        enabled: !libraryController.isEmpty
                                                 && !libraryController.archiveBusy
                                        onClicked: libraryController.copyAllInformation()
                                    }
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Export all"
                                        leftPadding: 9
                                        rightPadding: 9
                                        font.pixelSize: 11
                                        enabled: !libraryController.isEmpty
                                                 && !libraryController.archiveBusy
                                        onClicked: fileDialogController.saveLibraryArchive(
                                            "libraryExportAll",
                                            "Export all saved identities and private keys",
                                            "Quest APK Renamer Library.qarlib",
                                            libraryController.libraryPath
                                        )
                                    }
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Import"
                                        leftPadding: 9
                                        rightPadding: 9
                                        font.pixelSize: 11
                                        enabled: !libraryController.archiveBusy
                                        onClicked: fileDialogController.chooseLibraryArchive(
                                            "libraryImport",
                                            "Import saved identities and private keys",
                                            libraryController.libraryPath
                                        )
                                    }
                                }
                            }
                            Text {
                                text: "Headset"
                                color: libraryController.showInstalled
                                       ? window.textPrimary : window.textSecondary
                                font.pixelSize: 10
                            }
                            AppSwitch {
                                checked: libraryController.showInstalled
                                enabled: !appController.isBusy
                                         && !libraryController.archiveBusy
                                Accessible.name: "Show apps installed on headset"
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: "Switch between the connected headset's apps and the saved signing-key vault"
                                onToggled: libraryController.setShowInstalled(checked)
                            }
                            Item {
                                Layout.preferredWidth: 88
                                Layout.preferredHeight: 36
                                AppButton {
                                    anchors.fill: parent
                                    visible: libraryController.showInstalled
                                    text: libraryController.isLoading ? "Refreshing…" : "Refresh"
                                    primary: true
                                    enabled: libraryController.isConnected
                                             && !libraryController.isLoading
                                             && !appController.isBusy
                                    onClicked: libraryController.refresh()
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 3
                            color: window.panel
                            border.width: 1
                            border.color: window.line

                            ColumnLayout {
                                visible: libraryController.isEmpty
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 70, 480)
                                spacing: 12
                                BusyIndicator {
                                    visible: libraryController.showInstalled
                                             && libraryController.isLoading
                                    running: visible
                                    Layout.alignment: Qt.AlignHCenter
                                    Layout.preferredWidth: 30
                                    Layout.preferredHeight: 30
                                }
                                Rectangle {
                                    visible: !libraryController.showInstalled
                                             || !libraryController.isLoading
                                    Layout.alignment: Qt.AlignHCenter
                                    Layout.preferredWidth: 34
                                    Layout.preferredHeight: 34
                                    radius: 17
                                    color: "#24242a"
                                    Text {
                                        anchors.centerIn: parent
                                        text: !libraryController.showInstalled
                                              ? "•"
                                              : libraryController.isConnected ? "•" : "—"
                                        color: libraryController.errorMessage ? "#e3b74a" : "#777777"
                                        font.pixelSize: 18
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: libraryController.statusText
                                    color: window.textPrimary
                                    font.pixelSize: 12
                                    font.weight: Font.Medium
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    visible: !libraryController.showInstalled
                                             || !libraryController.isLoading
                                    Layout.fillWidth: true
                                    text: !libraryController.showInstalled
                                          ? "Build a signed game and its app ID and signing key will be saved here automatically."
                                          : !libraryController.isConnected
                                          ? "Keep the headset awake and approve USB debugging when prompted."
                                          : libraryController.errorMessage
                                          ? "The rest of the app is still available. Reconnect the headset or try again."
                                          : "Only user-installed apps are shown; system packages are hidden."
                                    color: window.textSecondary
                                    font.pixelSize: 10
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                }
                                AppButton {
                                    visible: libraryController.showInstalled
                                             && libraryController.isConnected
                                             && !libraryController.isLoading
                                    Layout.alignment: Qt.AlignHCenter
                                    text: "Try again"
                                    primary: Boolean(libraryController.errorMessage)
                                    onClicked: libraryController.refresh()
                                }
                            }

                            ListView {
                                id: libraryList
                                visible: !libraryController.isEmpty
                                anchors.fill: parent
                                anchors.margins: 1
                                clip: true
                                model: libraryController.rows
                                reuseItems: true
                                cacheBuffer: 188
                                boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: AppScrollBar {}
                                keyNavigationEnabled: true
                                focus: true
                                Keys.onUpPressed: libraryController.selectOffset(-1)
                                Keys.onDownPressed: libraryController.selectOffset(1)
                                delegate: Rectangle {
                                            required property var modelData
                                            width: libraryList.width
                                            height: libraryController.showInstalled ? 86 : 94
                                            color: libraryController.selectedId === modelData.id
                                                   ? "#24242a"
                                                   : rowMouse.containsMouse ? "#202025" : "transparent"
                                            Behavior on color { ColorAnimation { duration: 100 } }

                                            Rectangle {
                                                anchors.bottom: parent.bottom
                                                anchors.left: parent.left
                                                anchors.right: parent.right
                                                height: 1
                                                color: window.line
                                            }
                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.leftMargin: 16
                                                anchors.rightMargin: 10
                                                spacing: 12
                                                Rectangle {
                                                    Layout.preferredWidth: 40
                                                    Layout.preferredHeight: 40
                                                    radius: 8
                                                    color: "#2b2b31"
                                                    border.width: 1
                                                    border.color: "#3a3a43"
                                                    clip: true
                                                    Image {
                                                        id: libraryIconImage
                                                        anchors.fill: parent
                                                        anchors.margins: 2
                                                        source: modelData.iconUrl || ""
                                                        fillMode: Image.PreserveAspectFit
                                                        asynchronous: true
                                                        cache: true
                                                        // Decode launcher icons at display size, not 512 px.
                                                        sourceSize: Qt.size(80, 80)
                                                    }
                                                    Text {
                                                        visible: !modelData.iconUrl
                                                        anchors.centerIn: parent
                                                        text: modelData.gameName
                                                              ? modelData.gameName.charAt(0).toUpperCase()
                                                              : "?"
                                                        color: "#999999"
                                                        font.pixelSize: 15
                                                        font.weight: Font.DemiBold
                                                    }
                                                }
                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 4
                                                    RowLayout {
                                                        Layout.fillWidth: true
                                                        spacing: 8
                                                        Text {
                                                            Layout.fillWidth: true
                                                            text: modelData.gameName
                                                            color: window.textPrimary
                                                            font.pixelSize: 13
                                                            font.weight: Font.DemiBold
                                                            elide: Text.ElideRight
                                                        }
                                                        Rectangle {
                                                            implicitWidth: libraryStatus.implicitWidth + 16
                                                            implicitHeight: 22
                                                            radius: 11
                                                            color: libraryController.showInstalled
                                                                   ? (modelData.managed ? "#263b32" : "#2e2e35")
                                                                   : (modelData.keyReady ? "#263b32" : "#332e14")
                                                            Text {
                                                                id: libraryStatus
                                                                anchors.centerIn: parent
                                                                text: modelData.status
                                                                color: libraryController.showInstalled
                                                                       ? (modelData.managed ? "#78b894" : "#a8a8a8")
                                                                       : (modelData.keyReady ? "#78b894" : "#e3b74a")
                                                                font.pixelSize: 9
                                                                font.weight: Font.DemiBold
                                                            }
                                                        }
                                                    }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: libraryController.showInstalled
                                                              ? modelData.targetPackage
                                                              : "Original   " + modelData.originalPackage
                                                        color: window.textSecondary
                                                        font.pixelSize: 10
                                                        elide: Text.ElideMiddle
                                                    }
                                                    Text {
                                                        visible: !libraryController.showInstalled
                                                        Layout.fillWidth: true
                                                        text: "Renamed  " + modelData.targetPackage
                                                        color: "#b9b9b9"
                                                        font.pixelSize: 10
                                                        elide: Text.ElideMiddle
                                                    }
                                                }
                                                ColumnLayout {
                                                    spacing: 4
                                                    Text {
                                                        visible: Boolean(modelData.versionText)
                                                        Layout.alignment: Qt.AlignRight
                                                        text: modelData.versionText
                                                        color: window.textSecondary
                                                        font.pixelSize: 10
                                                    }
                                                    Text {
                                                        Layout.alignment: Qt.AlignRight
                                                        text: modelData.keyStatus
                                                        color: !libraryController.showInstalled
                                                               ? (modelData.keyReady ? "#78b894" : "#e3b74a")
                                                               : modelData.managed
                                                               ? (modelData.keyReady ? "#78b894" : "#e3b74a")
                                                               : "#888888"
                                                        font.pixelSize: 10
                                                    }
                                                }
                                                AppButton {
                                                    visible: libraryController.showInstalled
                                                    text: "Select"
                                                    primary: libraryController.selectedId === modelData.id
                                                    enabled: !appController.isBusy
                                                    onClicked: libraryController.select(modelData.id)
                                                }
                                            }
                                            MouseArea {
                                                id: rowMouse
                                                anchors.fill: parent
                                                anchors.rightMargin: libraryController.showInstalled ? 92 : 0
                                                enabled: true
                                                hoverEnabled: true
                                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                                onClicked: libraryController.select(modelData.id)
                                            }
                                }
                            }
                        }

                        Rectangle {
                            visible: !libraryController.showInstalled
                                     && !libraryController.isEmpty
                            Layout.fillWidth: true
                            Layout.preferredHeight: visible ? 144 : 0
                            radius: 3
                            color: window.panel
                            border.width: 1
                            border.color: window.line
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 15
                                spacing: 18
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    Text {
                                        text: (libraryController.selected.gameName || "SAVED IDENTITY").toUpperCase()
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: (libraryController.selected.originalPackage || "")
                                              + "  →  "
                                              + (libraryController.selected.targetPackage || "")
                                        color: window.textPrimary
                                        font.pixelSize: 12
                                        font.weight: Font.Medium
                                        elide: Text.ElideMiddle
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: (libraryController.selected.keyStatus || "")
                                              + (libraryController.selected.keySha256
                                                 ? "  •  SHA-256 " + libraryController.selected.keySha256
                                                 : "")
                                        color: libraryController.selected.keyReady ? "#78b894" : "#e3b74a"
                                        font.pixelSize: 10
                                        elide: Text.ElideMiddle
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: libraryController.selected.keyPath || "No signing-key file is saved."
                                        color: window.textSecondary
                                        font.pixelSize: 10
                                        elide: Text.ElideMiddle
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "This app ID and signing identity are reused automatically when a matching source is selected."
                                        color: window.textSecondary
                                        font.pixelSize: 10
                                        wrapMode: Text.WordWrap
                                    }
                                }
                                GridLayout {
                                    Layout.preferredWidth: 280
                                    columns: 2
                                    columnSpacing: 7
                                    rowSpacing: 7
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Copy info"
                                        enabled: !libraryController.archiveBusy
                                        onClicked: libraryController.copySelectedInformation()
                                    }
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Export identity"
                                        enabled: !libraryController.archiveBusy
                                        onClicked: fileDialogController.saveLibraryArchive(
                                            "libraryExportSelected",
                                            "Export this saved identity and private key",
                                            (libraryController.selected.targetPackage || "Saved identity") + ".qarlib",
                                            libraryController.libraryPath
                                        )
                                    }
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Open key folder"
                                        enabled: Boolean(libraryController.selected.keyPath)
                                                 && !libraryController.archiveBusy
                                        onClicked: libraryController.openSelectedKeyFolder()
                                    }
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Remove"
                                        danger: true
                                        enabled: !libraryController.archiveBusy
                                        onClicked: libraryDeleteDialog.open()
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: libraryController.showInstalled
                                     && !libraryController.isEmpty
                                     && libraryController.isConnected
                            Layout.fillWidth: true
                            Layout.preferredHeight: visible ? 122 : 0
                            radius: 3
                            color: window.panel
                            border.width: 1
                            border.color: window.line
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 15
                                spacing: 18
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    Text {
                                        text: "UPDATE " + (libraryController.selected.gameName || "APP").toUpperCase()
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: libraryController.selected.updateHelp || "Choose an update source."
                                        color: window.textPrimary
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: libraryController.selected.managed
                                              ? "The app will be rebuilt with its saved identity before installation."
                                              : "The APK is installed unchanged so Android can verify its signature. Choose a folder to include OBB files."
                                        color: window.textSecondary
                                        font.pixelSize: 10
                                        elide: Text.ElideMiddle
                                    }
                                }
                                ColumnLayout {
                                    spacing: 8
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Choose update APK…"
                                        enabled: libraryController.selectedId
                                                 && !appController.isBusy
                                        onClicked: {
                                            appController.prepareLibraryUpdate(libraryController.selectedId)
                                            fileDialogController.chooseApk(
                                                "libraryUpdate",
                                                "Choose the newer game APK",
                                                libraryController.selected.sourcePath || ""
                                            )
                                        }
                                    }
                                    AppButton {
                                        Layout.fillWidth: true
                                        text: "Choose update folder…"
                                        primary: true
                                        enabled: libraryController.selectedId
                                                 && !appController.isBusy
                                        onClicked: {
                                            appController.prepareLibraryUpdate(libraryController.selectedId)
                                            fileDialogController.chooseFolder(
                                                "libraryUpdate",
                                                "Choose the newer game folder",
                                                libraryController.selected.sourcePath || ""
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Bulk page
                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: window.pageMargin
                        anchors.rightMargin: window.pageMargin
                        anchors.topMargin: 16
                        anchors.bottomMargin: 26
                        spacing: 12

                        RowLayout {
                            Layout.fillWidth: true
                            Item { Layout.fillWidth: true }
                            AppButton {
                                text: "Add APKs…"
                                primary: true
                                enabled: !bulkController.isBusy && !appController.isBusy
                                tip: "Add one or more APK files; each becomes a queue entry"
                                onClicked: fileDialogController.chooseApks(
                                    "bulkApks",
                                    "Add one or more Quest APKs",
                                    appController.folderPath || appController.lastSourceFolder
                                )
                            }
                            AppButton {
                                text: "Add folder…"
                                enabled: !bulkController.isBusy && !appController.isBusy
                                tip: "Add one game folder containing an APK and its OBB files"
                                onClicked: fileDialogController.chooseFolder(
                                    "bulkFolder",
                                    "Add a game folder",
                                    appController.folderPath || appController.lastSourceFolder
                                )
                            }
                            AppButton {
                                text: "Scan parent…"
                                enabled: !bulkController.isBusy && !appController.isBusy
                                tip: "Add every game folder found directly inside a parent folder"
                                onClicked: fileDialogController.chooseFolder(
                                    "bulkScan",
                                    "Scan a parent containing game folders",
                                    appController.folderPath || appController.lastSourceFolder
                                )
                            }
                        }

                        Panel {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 220
                            color: bulkDrop.containsDrag ? "#202025" : window.panel
                            border.color: bulkDrop.containsDrag ? window.accent : window.line
                            Behavior on color { ColorAnimation { duration: 100 } }

                            DropArea {
                                id: bulkDrop
                                anchors.fill: parent
                                enabled: !bulkController.isBusy && !appController.isBusy
                                onDropped: drop => {
                                    if (drop.hasUrls)
                                        bulkController.addDropped(drop.urls)
                                }
                            }

                            ListView {
                                id: bulkList
                                anchors.fill: parent
                                anchors.margins: 1
                                clip: true
                                spacing: 1
                                model: bulkController.items
                                visible: bulkController.count > 0
                                reuseItems: true
                                boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: AppScrollBar {}

                                delegate: Rectangle {
                                    id: bulkRow
                                    required property int index
                                    required property string folderName
                                    required property string folderPath
                                    required property string apkName
                                    required property string obbSummary
                                    required property string currentPackage
                                    required property string targetPackage
                                    required property string itemStatus
                                    required property string itemDetail
                                    required property string itemTone
                                    required property real itemProgress
                                    required property bool itemBuilt
                                    required property bool itemInstalled
                                    width: bulkList.width
                                    height: 92
                                    color: index % 2 ? "#1b1b1f" : "#1d1d21"

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 16
                                        anchors.rightMargin: 10
                                        spacing: 12
                                        Rectangle {
                                            Layout.preferredWidth: 8
                                            Layout.preferredHeight: 8
                                            radius: 4
                                            color: window.toneColor(bulkRow.itemTone, "#737373")
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Text {
                                                    Layout.maximumWidth: Math.max(120, bulkRow.width * 0.45)
                                                    text: bulkRow.folderName
                                                    color: window.textPrimary
                                                    font.pixelSize: 13
                                                    font.weight: Font.DemiBold
                                                    elide: Text.ElideMiddle
                                                }
                                                Text {
                                                    text: bulkRow.apkName + "  •  " + bulkRow.obbSummary
                                                    color: "#777777"
                                                    font.pixelSize: 10
                                                    Layout.fillWidth: true
                                                    elide: Text.ElideRight
                                                }
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: bulkRow.currentPackage + "  →  " + bulkRow.targetPackage
                                                color: "#a9a9a9"
                                                font.pixelSize: 11
                                                elide: Text.ElideMiddle
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: bulkRow.itemDetail
                                                color: bulkRow.itemTone === "error" ? "#e88780" : "#777777"
                                                font.pixelSize: 10
                                                elide: Text.ElideRight
                                                ToolTip.visible: detailHover.containsMouse && truncated
                                                ToolTip.text: bulkRow.itemDetail
                                                ToolTip.delay: 400
                                                MouseArea {
                                                    id: detailHover
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    acceptedButtons: Qt.NoButton
                                                }
                                            }
                                        }
                                        Rectangle {
                                            Layout.preferredWidth: statusText.implicitWidth + 18
                                            Layout.preferredHeight: 26
                                            radius: 13
                                            color: bulkRow.itemTone === "success" ? "#263c32"
                                                 : bulkRow.itemTone === "error" ? "#402424"
                                                 : bulkRow.itemTone === "warning" ? "#3a3418"
                                                 : "#2b2b31"
                                            Text {
                                                id: statusText
                                                anchors.centerIn: parent
                                                text: bulkRow.itemStatus
                                                color: "#d0d0d0"
                                                font.pixelSize: 10
                                                font.weight: Font.Medium
                                            }
                                        }
                                        AppButton {
                                            visible: bulkRow.itemBuilt
                                            text: "Open"
                                            quiet: true
                                            tip: "Open this game's finished output folder"
                                            onClicked: bulkController.openOutput(bulkRow.index)
                                        }
                                        AppButton {
                                            visible: bulkRow.itemTone === "error" && !bulkController.isBusy
                                            text: "Copy error"
                                            quiet: true
                                            tip: "Copy this entry's error message"
                                            onClicked: bulkController.copyDetail(bulkRow.index)
                                        }
                                        AppButton {
                                            text: "Remove"
                                            quiet: true
                                            enabled: !bulkController.isBusy
                                            onClicked: bulkController.removeItem(bulkRow.index)
                                        }
                                    }
                                    ThinProgress {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        visible: bulkRow.itemProgress > 0 && bulkRow.itemProgress < 1
                                        value: bulkRow.itemProgress
                                        fillColor: window.accent
                                    }
                                }
                            }

                            Column {
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 80, 430)
                                spacing: 10
                                visible: bulkController.count === 0
                                Text {
                                    width: parent.width
                                    text: "No games in the queue"
                                    color: window.textPrimary
                                    font.pixelSize: 17
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                Text {
                                    width: parent.width
                                    text: "Drop several game folders here, select multiple APKs, or scan one parent folder."
                                    color: window.textSecondary
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    horizontalAlignment: Text.AlignHCenter
                                    lineHeight: 1.25
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: bulkController.hasOverview ? 66 : 0
                            visible: bulkController.hasOverview
                            radius: 3
                            color: "#202722"
                            border.width: 1
                            border.color: "#3d5747"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 8
                                spacing: 10
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text { text: bulkController.overviewTitle; color: "#d8e6dd"; font.pixelSize: 12; font.weight: Font.DemiBold }
                                    Text { text: bulkController.overviewText; color: "#91a398"; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                                AppButton { text: "Dismiss"; quiet: true; onClicked: bulkController.dismissOverview() }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 112
                            radius: 3
                            color: window.panel
                            border.width: 1
                            border.color: window.line
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: 24
                                ColumnLayout {
                                    Layout.minimumWidth: 200
                                    Layout.preferredWidth: 300
                                    Layout.maximumWidth: 340
                                    Layout.fillHeight: true
                                    spacing: 5
                                    Text { text: "PACKAGE ID SUFFIX"; color: "#777777"; font.pixelSize: 9; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                                    TextField {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 34
                                        text: bulkController.suffix
                                        enabled: bulkController.canEditSuffix
                                        color: window.textPrimary
                                        selectByMouse: true
                                        onTextEdited: bulkController.setSuffix(text)
                                        background: Rectangle { color: "#161619"; border.width: 1; border.color: bulkController.suffixError ? "#6f3835" : "#3a3a43"; radius: 3 }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: bulkController.suffixError || "Example: com.studio.game + a → com.studio.gamea"
                                        color: bulkController.suffixError ? "#e88780" : "#777777"
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                }
                                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: window.line }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 0
                                    SettingRow {
                                        Layout.fillWidth: true
                                        compact: true
                                        enabled: !bulkController.isBusy
                                        title: "Replace each source after its build"
                                        detail: "Every replacement is staged, verified, and rollback-protected"
                                        checked: bulkController.replaceSources
                                        onChanged: value => bulkController.setReplaceSources(value)
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        compact: true
                                        enabled: !bulkController.isBusy
                                        title: "Delete each installed folder after success"
                                        detail: "App-created outputs only, after APK and OBB verification"
                                        checked: bulkController.cleanupAfterInstall
                                        onChanged: value => bulkController.setCleanupAfterInstall(value)
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: bulkController.countLabel + "  •  " + bulkController.status
                                      + (bulkController.isBusy
                                         ? "  •  " + Math.round(bulkController.progress * 100) + "%"
                                         : "")
                                color: "#838383"
                                font.pixelSize: 10
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                            Item { Layout.fillWidth: true }
                            AppButton {
                                text: bulkController.isBusy ? "Cancel safely" : "Build queue"
                                primary: !bulkController.isBusy
                                enabled: bulkController.isBusy
                                         || (bulkController.canBuild && !appController.isBusy)
                                onClicked: bulkController.isBusy ? bulkController.cancel() : bulkController.requestBuild()
                            }
                            AppButton {
                                text: "Install queue"
                                primary: true
                                enabled: !bulkController.isBusy
                                         && !appController.isBusy
                                         && bulkController.canInstall
                                onClicked: bulkController.requestInstall()
                            }
                            AppButton {
                                visible: bulkController.hasInstalled
                                text: "Remove finished"
                                quiet: true
                                enabled: !bulkController.isBusy
                                tip: "Drop installed games from the queue"
                                onClicked: bulkController.removeFinished()
                            }
                            AppButton {
                                text: "Clear"
                                enabled: !bulkController.isBusy && bulkController.count > 0
                                onClicked: bulkController.clear()
                            }
                        }
                        ThinProgress {
                            Layout.fillWidth: true
                            Layout.preferredHeight: bulkController.isBusy ? 2 : 0
                            visible: bulkController.isBusy
                            value: bulkController.progress
                            fillColor: window.accent
                        }
                    }
                }

                // APK Inspector
                InspectorPage {
                    textPrimary: window.textPrimary
                    textSecondary: window.textSecondary
                    line: window.line
                    panel: window.panel
                    accent: window.accent
                    pageMargin: window.pageMargin
                }

                // Settings page
                Item {
                    PageScroller {
                        id: settingsScroll
                        anchors.fill: parent
                        page: settingsColumn

                        ColumnLayout {
                            id: settingsColumn
                            x: window.pageMargin
                            y: settingsScroll.topInset
                            width: settingsScroll.width - 2 * window.pageMargin
                            spacing: 18

                            Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: toolsColumn.implicitHeight + 36
                                ColumnLayout {
                                    id: toolsColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 18
                                    spacing: 8
                                    RowLayout {
                                        Layout.fillWidth: true
                                        SectionLabel { text: "ANDROID TOOLS" }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: toolController.allReady ? "READY" : "NEEDS ATTENTION"
                                            color: toolController.allReady ? "#78b894" : "#e3b74a"
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 0.6
                                        }
                                    }
                                    Repeater {
                                        model: toolController.toolRows
                                        delegate: RowLayout {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 27
                                            spacing: 9
                                            Rectangle {
                                                Layout.preferredWidth: 7
                                                Layout.preferredHeight: 7
                                                radius: 4
                                                color: modelData.status === "ready" ? "#70b18f"
                                                     : modelData.status === "damaged" ? "#e5706a"
                                                     : "#e3b74a"
                                            }
                                            Text {
                                                Layout.maximumWidth: toolsColumn.width * 0.5
                                                text: modelData.label + " " + modelData.version
                                                color: window.textPrimary
                                                font.pixelSize: 12
                                                font.weight: Font.Medium
                                                elide: Text.ElideRight
                                            }
                                            Item { Layout.fillWidth: true }
                                            Text {
                                                Layout.maximumWidth: toolsColumn.width * 0.5
                                                text: modelData.detail
                                                color: window.textSecondary
                                                font.pixelSize: 11
                                                elide: Text.ElideMiddle
                                                ToolTip.visible: toolDetailHover.containsMouse && truncated
                                                ToolTip.text: modelData.detail
                                                ToolTip.delay: 400
                                                MouseArea {
                                                    id: toolDetailHover
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    acceptedButtons: Qt.NoButton
                                                }
                                            }
                                        }
                                    }
                                    ThinProgress {
                                        Layout.fillWidth: true
                                        thickness: toolController.isBusy ? 2 : 1
                                        value: toolController.isBusy ? toolController.progress : 0
                                        color: "#2d2d34"
                                        fillColor: window.accent
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 12
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 2
                                            Text {
                                                Layout.fillWidth: true
                                                text: toolController.status
                                                      + (toolController.isBusy
                                                         ? "  " + Math.round(toolController.progress * 100) + "%"
                                                         : "")
                                                color: toolController.tone === "error" ? "#e88780"
                                                     : toolController.tone === "success" ? "#78b894"
                                                     : toolController.tone === "warning" ? "#e3b74a"
                                                     : window.textSecondary
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: "Downloads only pinned Apktool and signer files; Java and ADB use the packaged or system copies."
                                                color: "#737373"
                                                font.pixelSize: 10
                                                elide: Text.ElideRight
                                            }
                                        }
                                        AppButton {
                                            text: toolController.actionLabel
                                            enabled: !toolController.isBusy
                                            onClicked: toolController.runAction()
                                        }
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: buildDefaultsColumn.implicitHeight + 36
                                ColumnLayout {
                                    id: buildDefaultsColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 18
                                    spacing: 0
                                    SectionLabel {
                                        text: "BUILD DEFAULTS"
                                        Layout.bottomMargin: 8
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        title: "Copy and rename OBB files"
                                        detail: "Keep expansion data paired with the renamed package"
                                        checked: appController.settings.copyObbs
                                        onChanged: value => appController.setSetting("copy_obbs", value)
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        title: "Sign completed APKs"
                                        detail: "Use the persistent Quest APK Renamer signing identity"
                                        checked: appController.settings.signApks
                                        onChanged: value => appController.setSetting("sign_apks", value)
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        title: "Automatic preflight"
                                        detail: "Check tools, free space, files, and package conflicts"
                                        checked: appController.settings.automaticPreflight
                                        onChanged: value => appController.setSetting("automatic_preflight", value)
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        title: "Also rename Java packages (legacy)"
                                        detail: "Move code namespaces too. Refused automatically for apps whose native libraries bind to their Java classes"
                                        checked: appController.settings.renameJavaPackages
                                        onChanged: value => appController.setSetting("rename_java_packages", value)
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        title: "Change display name of renamed copies (experimental)"
                                        detail: "May cause errors in some apps. Adds a Display name field to the Dashboard and a default suffix below"
                                        checked: appController.settings.changeDisplayName
                                        onChanged: value => appController.setSetting("change_display_name", value)
                                    }
                                    RowLayout {
                                        visible: appController.settings.changeDisplayName
                                        Layout.fillWidth: true
                                        Layout.minimumHeight: 64
                                        Layout.preferredHeight: Math.max(64, implicitHeight + 12)
                                        spacing: 10
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3
                                            Text {
                                                text: "Display-name suffix"
                                                color: "#e2e2e2"
                                                font.pixelSize: 13
                                                font.weight: Font.Medium
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: appController.settings.labelSuffix
                                                      ? "Copies appear as “Game " + appController.settings.labelSuffix + "” — may cause errors in some apps"
                                                      : "No suffix: copies keep the original name unless a Display name is typed on the Dashboard"
                                                color: appController.settings.labelSuffix ? "#e3b74a" : "#8a8a8a"
                                                font.pixelSize: 11
                                                wrapMode: Text.WordWrap
                                            }
                                        }
                                        Repeater {
                                            model: ["(Dev)", "(Test)", "2"]
                                            delegate: AppButton {
                                                required property string modelData
                                                text: modelData
                                                implicitHeight: 30
                                                leftPadding: 9
                                                rightPadding: 9
                                                font.pixelSize: 11
                                                primary: appController.settings.labelSuffix === modelData
                                                onClicked: appController.setLabelSuffix(
                                                    appController.settings.labelSuffix === modelData ? "" : modelData)
                                            }
                                        }
                                        TextField {
                                            id: labelSuffixField
                                            Layout.preferredWidth: 110
                                            Layout.preferredHeight: 30
                                            text: appController.settings.labelSuffix
                                            placeholderText: "none"
                                            color: window.textPrimary
                                            font.pixelSize: 12
                                            selectByMouse: true
                                            leftPadding: 9
                                            rightPadding: 9
                                            onEditingFinished: {
                                                if (text !== appController.settings.labelSuffix)
                                                    appController.setLabelSuffix(text)
                                            }
                                            background: Rectangle {
                                                radius: 3
                                                color: "#131316"
                                                border.width: 1
                                                border.color: labelSuffixField.activeFocus ? window.accent : "#3e3e48"
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 64
                                        spacing: 10
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3
                                            Text {
                                                text: "Default app ID tag"
                                                color: "#e2e2e2"
                                                font.pixelSize: 13
                                                font.weight: Font.Medium
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: "Tag inserted into newly selected package IDs, e.g. com."
                                                      + appController.settings.defaultTag + ".studio.game"
                                                color: "#848484"
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }
                                        }
                                        Repeater {
                                            model: ["mr", "dev", "test", "qa"]
                                            delegate: AppButton {
                                                required property string modelData
                                                text: "." + modelData
                                                implicitHeight: 30
                                                leftPadding: 9
                                                rightPadding: 9
                                                font.pixelSize: 11
                                                primary: appController.settings.defaultTag === modelData
                                                onClicked: appController.setDefaultTag(modelData)
                                            }
                                        }
                                        TextField {
                                            id: defaultTagField
                                            Layout.preferredWidth: 110
                                            Layout.preferredHeight: 30
                                            text: appController.settings.defaultTag
                                            placeholderText: "custom"
                                            color: window.textPrimary
                                            font.pixelSize: 12
                                            selectByMouse: true
                                            leftPadding: 9
                                            rightPadding: 9
                                            onEditingFinished: {
                                                if (text !== appController.settings.defaultTag)
                                                    appController.setDefaultTag(text)
                                            }
                                            background: Rectangle {
                                                radius: 3
                                                color: "#131316"
                                                border.width: 1
                                                border.color: defaultTagField.activeFocus ? window.accent : "#3e3e48"
                                            }
                                        }
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: cleanupRow.implicitHeight + 36
                                RowLayout {
                                    id: cleanupRow
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 18
                                    spacing: 16
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        SectionLabel { text: "OLD OUTPUT CLEANUP" }
                                        Text {
                                            Layout.fillWidth: true
                                            text: "Move a finished folder created by this app to Trash after a report safety check."
                                            color: window.textSecondary
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                        }
                                    }
                                    AppButton {
                                        text: "Choose old output…"
                                        enabled: !appController.isBusy
                                        onClicked: fileDialogController.chooseFolder(
                                            "cleanupOutput",
                                            "Choose an old Quest APK Renamer output",
                                            appController.outputFolder
                                        )
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: appColumn.implicitHeight + 36
                                ColumnLayout {
                                    id: appColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 18
                                    spacing: 0
                                    SectionLabel {
                                        text: "APP"
                                        Layout.bottomMargin: 8
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        title: "Check for updates"
                                        detail: "Include stable and preview releases"
                                        checked: appController.settings.checkUpdates
                                        onChanged: value => appController.setSetting("check_updates", value)
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 54
                                        Layout.topMargin: 4
                                        Layout.bottomMargin: 4
                                        spacing: 14
                                        Text {
                                            Layout.fillWidth: true
                                            text: updateController.status
                                            color: updateController.tone === "success" ? "#78b894"
                                                 : updateController.tone === "warning" ? "#e3b74a"
                                                 : window.textSecondary
                                            font.pixelSize: 11
                                            elide: Text.ElideRight
                                        }
                                        AppButton {
                                            text: updateController.isBusy ? "Checking…" : "Check now"
                                            Layout.preferredWidth: 108
                                            Layout.preferredHeight: 36
                                            enabled: !updateController.isBusy
                                            onClicked: updateController.checkNow()
                                        }
                                    }
                                    SettingRow {
                                        Layout.fillWidth: true
                                        title: "Signing-key backup reminder"
                                        detail: "Remind me until the persistent key is backed up"
                                        checked: appController.settings.keyBackupReminder
                                        onChanged: value => appController.setSetting("key_backup_reminder", value)
                                    }
                                }
                            }

                            Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: signingColumn.implicitHeight + 36
                                ColumnLayout {
                                    id: signingColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 18
                                    spacing: 8
                                    SectionLabel { text: "SIGNING IDENTITY" }
                                    Text {
                                        Layout.fillWidth: true
                                        text: appController.signingStatus
                                        color: "#a5a5a5"
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                    }
                                    SectionLabel {
                                        text: "DEFAULT BACKUP LOCATION"
                                        Layout.topMargin: 3
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 32
                                            radius: 3
                                            color: defaultBackupMouse.containsMouse ? "#232328" : "#1e1e22"
                                            border.width: 1
                                            border.color: defaultBackupMouse.containsMouse ? "#494954" : "#32323a"
                                            Text {
                                                anchors.left: parent.left
                                                anchors.right: parent.right
                                                anchors.verticalCenter: parent.verticalCenter
                                                anchors.margins: 10
                                                text: appController.settings.keyBackupFolder
                                                      || "Not set — ask after the first signed build"
                                                color: appController.settings.keyBackupFolder
                                                       ? window.textSecondary : "#777777"
                                                font.pixelSize: 10
                                                elide: Text.ElideMiddle
                                            }
                                            MouseArea {
                                                id: defaultBackupMouse
                                                anchors.fill: parent
                                                enabled: !appController.isBusy
                                                hoverEnabled: true
                                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                                onClicked: fileDialogController.chooseFolder(
                                                    "defaultKeyBackup",
                                                    "Choose the default signing-key backup location",
                                                    appController.settings.keyBackupFolder
                                                    || appController.folderPath
                                                )
                                            }
                                        }
                                        AppButton {
                                            text: appController.settings.keyBackupFolder ? "Change…" : "Choose…"
                                            enabled: !appController.isBusy
                                            onClicked: fileDialogController.chooseFolder(
                                                "defaultKeyBackup",
                                                "Choose the default signing-key backup location",
                                                appController.settings.keyBackupFolder
                                                || appController.folderPath
                                            )
                                        }
                                        AppButton {
                                            visible: Boolean(appController.settings.keyBackupFolder)
                                            text: "Clear"
                                            quiet: true
                                            enabled: !appController.isBusy
                                            onClicked: appController.clearDefaultKeyBackupFolder()
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        AppButton {
                                            text: "Back up key…"
                                            enabled: appController.canBackupSigningKey
                                            onClicked: fileDialogController.chooseFolder(
                                                "signingBackup",
                                                "Choose where to save the private signing-key backup",
                                                appController.folderPath
                                            )
                                        }
                                        AppButton {
                                            text: "Restore backup…"
                                            enabled: appController.canRestoreSigningKey
                                            onClicked: fileDialogController.chooseFolder(
                                                "signingRestore",
                                                "Choose a signing-key backup folder",
                                                appController.folderPath
                                            )
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                }
                            }

                            Panel {
                                visible: appController.wirelessSupported
                                Layout.fillWidth: true
                                Layout.preferredHeight: wirelessColumn.implicitHeight + 36
                                ColumnLayout {
                                    id: wirelessColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 18
                                    spacing: 10
                                    RowLayout {
                                        Layout.fillWidth: true
                                        SectionLabel { text: "WIRELESS ADB" }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: appController.isWirelessDevice ? "CONNECTED OVER WI-FI"
                                                : appController.wirelessBusy ? "WORKING…" : ""
                                            color: appController.isWirelessDevice ? "#78b894" : "#9a9a9a"
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 0.6
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Connect the headset by USB once and press Enable over USB, or enter the "
                                              + "address shown in the headset's Wireless debugging settings. The Quest "
                                              + "must be on the same Wi-Fi network and stays reachable until it reboots. "
                                              + "Every successful connection is saved below."
                                        color: window.textSecondary
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        TextField {
                                            id: wirelessField
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 34
                                            text: appController.settings.lastWirelessAddress
                                            placeholderText: "192.168.1.20:5555  (or paste an adb connect line)"
                                            color: window.textPrimary
                                            font.pixelSize: 12
                                            selectByMouse: true
                                            leftPadding: 10
                                            rightPadding: 10
                                            enabled: !appController.wirelessBusy
                                            onAccepted: appController.connectWireless(text)
                                            background: Rectangle {
                                                radius: 3
                                                color: "#131316"
                                                border.width: 1
                                                border.color: wirelessField.activeFocus ? window.accent : "#3e3e48"
                                            }
                                        }
                                        AppButton {
                                            text: "Connect"
                                            primary: true
                                            enabled: !appController.wirelessBusy && wirelessField.text.trim().length > 0
                                            tip: "adb connect to this address and remember it"
                                            onClicked: appController.connectWireless(wirelessField.text)
                                        }
                                        AppButton {
                                            text: "Enable over USB"
                                            enabled: !appController.wirelessBusy
                                                     && appController.deviceTone === "success"
                                                     && !appController.isWirelessDevice
                                            tip: "Switch the USB-connected headset to TCP/IP ADB on port 5555, connect, and remember it"
                                            onClicked: appController.enableWirelessOverUsb()
                                        }
                                    }

                                    // Saved Quests widget
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.topMargin: 4
                                        Layout.preferredHeight: savedColumn.implicitHeight + 2
                                        radius: 4
                                        color: "#151518"
                                        border.width: 1
                                        border.color: "#2f2f36"
                                        ColumnLayout {
                                            id: savedColumn
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.top: parent.top
                                            anchors.margins: 1
                                            spacing: 0
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 36
                                                Layout.leftMargin: 12
                                                Layout.rightMargin: 8
                                                spacing: 8
                                                SectionLabel {
                                                    text: "SAVED QUESTS  •  " + appController.savedWirelessDevices.length
                                                }
                                                Item { Layout.fillWidth: true }
                                                AppButton {
                                                    visible: appController.isWirelessDevice || appController.savedWirelessDevices.length > 0
                                                    text: "Disconnect all"
                                                    quiet: true
                                                    implicitHeight: 26
                                                    leftPadding: 9; rightPadding: 9
                                                    font.pixelSize: 11
                                                    enabled: !appController.wirelessBusy
                                                    tip: "adb disconnect — drops every wireless ADB session"
                                                    onClicked: appController.disconnectAllWireless()
                                                }
                                                AppButton {
                                                    visible: appController.savedWirelessDevices.length > 0
                                                    text: "Forget all"
                                                    quiet: true
                                                    danger: false
                                                    implicitHeight: 26
                                                    leftPadding: 9; rightPadding: 9
                                                    font.pixelSize: 11
                                                    enabled: !appController.wirelessBusy
                                                    onClicked: appController.forgetAllWirelessDevices()
                                                }
                                            }
                                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#2a2a30" }
                                            Text {
                                                visible: appController.savedWirelessDevices.length === 0
                                                Layout.fillWidth: true
                                                Layout.margins: 14
                                                text: "No saved Quests yet. Connect once — over USB with Enable over USB, or by address — and it appears here with its name, address, and last connection time."
                                                color: "#8f8f8f"
                                                font.pixelSize: 11
                                                wrapMode: Text.WordWrap
                                            }
                                            Repeater {
                                                model: appController.savedWirelessDevices
                                                delegate: Rectangle {
                                                    id: savedRow
                                                    required property var modelData
                                                    required property int index
                                                    readonly property bool isCurrent: appController.isWirelessDevice
                                                                                       && appController.currentSerial === modelData.address
                                                    Layout.fillWidth: true
                                                    Layout.preferredHeight: 56
                                                    color: index % 2 ? "#17171a" : "transparent"
                                                    RowLayout {
                                                        anchors.fill: parent
                                                        anchors.leftMargin: 12
                                                        anchors.rightMargin: 8
                                                        spacing: 10
                                                        Rectangle {
                                                            Layout.preferredWidth: 30
                                                            Layout.preferredHeight: 30
                                                            radius: 15
                                                            color: savedRow.isCurrent ? "#25382f" : "#25252b"
                                                            IconImage {
                                                                anchors.centerIn: parent
                                                                width: 14; height: 14
                                                                sourceSize.width: 14; sourceSize.height: 14
                                                                source: Qt.resolvedUrl("../assets/icon-wifi.svg")
                                                                color: savedRow.isCurrent ? "#70b18f" : "#9a9a9a"
                                                            }
                                                        }
                                                        ColumnLayout {
                                                            Layout.fillWidth: true
                                                            spacing: 2
                                                            RowLayout {
                                                                Layout.fillWidth: true
                                                                spacing: 8
                                                                TextField {
                                                                    id: savedLabel
                                                                    Layout.preferredWidth: 200
                                                                    Layout.preferredHeight: 26
                                                                    text: savedRow.modelData.label
                                                                    placeholderText: "Quest"
                                                                    color: window.textPrimary
                                                                    font.pixelSize: 12
                                                                    font.weight: Font.Medium
                                                                    selectByMouse: true
                                                                    leftPadding: 6
                                                                    rightPadding: 6
                                                                    onEditingFinished: {
                                                                        if (text !== savedRow.modelData.label)
                                                                            appController.renameWirelessDevice(savedRow.modelData.address, text)
                                                                    }
                                                                    background: Rectangle {
                                                                        radius: 3
                                                                        color: savedLabel.activeFocus || savedLabel.hovered ? "#131316" : "transparent"
                                                                        border.width: 1
                                                                        border.color: savedLabel.activeFocus ? window.accent
                                                                                    : savedLabel.hovered ? "#34343c" : "transparent"
                                                                    }
                                                                    ToolTip.visible: hovered && !activeFocus
                                                                    ToolTip.delay: 600
                                                                    ToolTip.text: "Click to rename"
                                                                }
                                                                Rectangle {
                                                                    visible: savedRow.isCurrent
                                                                    implicitWidth: connectedTag.implicitWidth + 14
                                                                    implicitHeight: 18
                                                                    radius: 9
                                                                    color: "#263b32"
                                                                    Text {
                                                                        id: connectedTag
                                                                        anchors.centerIn: parent
                                                                        text: "Connected"
                                                                        color: "#78b894"
                                                                        font.pixelSize: 9
                                                                        font.weight: Font.DemiBold
                                                                    }
                                                                }
                                                                Item { Layout.fillWidth: true }
                                                            }
                                                            Text {
                                                                Layout.fillWidth: true
                                                                Layout.leftMargin: 6
                                                                text: savedRow.modelData.address
                                                                      + (savedRow.modelData.last_connected
                                                                         ? "  •  last connected " + savedRow.modelData.last_connected
                                                                         : "")
                                                                color: "#8d8d8d"
                                                                font.pixelSize: 10
                                                                elide: Text.ElideMiddle
                                                            }
                                                        }
                                                        AppButton {
                                                            visible: !savedRow.isCurrent
                                                            text: "Connect"
                                                            implicitHeight: 28
                                                            leftPadding: 10; rightPadding: 10
                                                            font.pixelSize: 11
                                                            enabled: !appController.wirelessBusy
                                                            onClicked: appController.connectWireless(savedRow.modelData.address)
                                                        }
                                                        AppButton {
                                                            visible: savedRow.isCurrent
                                                            text: "Disconnect"
                                                            implicitHeight: 28
                                                            leftPadding: 10; rightPadding: 10
                                                            font.pixelSize: 11
                                                            enabled: !appController.wirelessBusy
                                                            onClicked: appController.disconnectWirelessAddress(savedRow.modelData.address)
                                                        }
                                                        AppButton {
                                                            text: "Copy"
                                                            quiet: true
                                                            implicitHeight: 28
                                                            leftPadding: 9; rightPadding: 9
                                                            font.pixelSize: 11
                                                            tip: "Copy an adb connect command for this Quest"
                                                            onClicked: appController.copyWirelessCommand(savedRow.modelData.address)
                                                        }
                                                        AppButton {
                                                            text: "Forget"
                                                            quiet: true
                                                            implicitHeight: 28
                                                            leftPadding: 9; rightPadding: 9
                                                            font.pixelSize: 11
                                                            enabled: !appController.wirelessBusy
                                                            onClicked: appController.forgetWirelessDevice(savedRow.modelData.address)
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        visible: appController.wirelessStatus.length > 0
                                        text: appController.wirelessStatus
                                        color: appController.wirelessTone === "error" ? "#e88780"
                                             : appController.wirelessTone === "success" ? "#78b894"
                                             : appController.wirelessTone === "warning" ? "#e3b74a"
                                             : window.textSecondary
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "Quest APK Renamer  •  v" + appVersion; color: "#747474"; font.pixelSize: 10 }
                                Item { Layout.fillWidth: true }
                                AppButton { text: "Copy support info"; onClicked: appController.copySupportInformation() }
                                AppButton { text: "Open data folder"; onClicked: appController.openDataFolder() }
                            }
                        }
                    }
                }
            }
        }
    }
}
