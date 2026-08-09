import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1160
    height: 800
    minimumWidth: 900
    minimumHeight: 640
    visible: true
    title: "Quest APK Renamer"
    color: "#171717"

    property color textPrimary: "#eeeeee"
    property color textSecondary: "#939393"
    property color line: "#353535"
    property color panel: "#1f1f1f"
    property color panelRaised: "#242424"
    property color accent: "#4c8abb"
    property int pageIndex: 0
    property int requestedPage: 0

    Shortcut { sequence: "Ctrl+1"; onActivated: window.showPage(0) }
    Shortcut { sequence: "Ctrl+2"; onActivated: window.showPage(1) }
    Shortcut { sequence: "Ctrl+3"; onActivated: window.showPage(2) }
    Shortcut { sequence: "Ctrl+4"; onActivated: window.showPage(3) }
    Shortcut { sequence: "Ctrl+5"; onActivated: window.showPage(4) }
    Shortcut { sequence: "Ctrl+L"; onActivated: logWindow.openWindow() }
    Shortcut {
        sequence: "Ctrl+O"
        onActivated: {
            window.showPage(0)
            fileDialogController.chooseFolder(
                "game",
                "Choose a Quest game folder",
                appController.folderPath
            )
        }
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
        }
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
        color: "#1b1b1b"

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
                implicitWidth: deviceContent.implicitWidth + 24
                implicitHeight: 32
                radius: 3
                color: "#242424"
                border.width: 1
                border.color: appController.deviceTone === "error" ? "#714743"
                            : appController.deviceTone === "warning" ? "#6c5d36"
                            : appController.deviceTone === "success" ? "#3d6654"
                            : "#414141"
                Row {
                    id: deviceContent
                    anchors.centerIn: parent
                    spacing: 8
                    Rectangle {
                        width: 8
                        height: 8
                        radius: 4
                        anchors.verticalCenter: parent.verticalCenter
                        color: appController.deviceTone === "error" ? "#d4776f"
                             : appController.deviceTone === "warning" ? "#d0b15b"
                             : appController.deviceTone === "success" ? "#70b18f"
                             : "#7d7d7d"
                    }
                    Text {
                        text: appController.deviceLabel
                        color: "#d0d0d0"
                        font.pixelSize: 12
                        font.weight: Font.Medium
                    }
                }
                MouseArea {
                    id: deviceMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: appController.refreshDevice()
                }
                ToolTip {
                    visible: deviceMouse.containsMouse
                    delay: 450
                    text: appController.deviceDetail + "\nClick to refresh."
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
            color: "#191919"

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
                    ScrollView {
                        anchors.fill: parent
                        contentWidth: availableWidth
                        clip: true

                        ColumnLayout {
                            width: parent.width
                            spacing: 16
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.leftMargin: 30
                            anchors.rightMargin: 30
                            anchors.topMargin: 16
                            anchors.bottomMargin: 28

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Item {
                                    Layout.fillWidth: true
                                }
                                AppButton {
                                    text: "Install built game"
                                    enabled: appController.canInstallBuilt
                                    onClicked: appController.installBuiltFolder()
                                }
                                AppButton {
                                    text: appController.installActionLabel
                                    enabled: appController.canInstallFolder
                                    onClicked: fileDialogController.chooseFolder(
                                        "install",
                                        "Choose a finished game folder",
                                        appController.outputFolder
                                    )
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 126
                                radius: 3
                                color: sourceDrop.containsDrag ? "#272727" : window.panel
                                border.width: 1
                                border.color: sourceDrop.containsDrag ? window.accent : window.line
                                Behavior on color { ColorAnimation { duration: 100 } }

                                DropArea {
                                    id: sourceDrop
                                    anchors.fill: parent
                                    onDropped: function(drop) {
                                        if (drop.urls.length > 0)
                                            appController.chooseFolder(drop.urls[0])
                                    }
                                }

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 7
                                    Text {
                                        text: "SOURCE"
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
                                    }
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
                                            onAccepted: appController.chooseFolderPath(text)
                                            onEditingFinished: {
                                                if (text && text !== appController.folderPath)
                                                    appController.chooseFolderPath(text)
                                            }
                                            background: Rectangle {
                                                radius: 3
                                                color: "#181818"
                                                border.width: 1
                                                border.color: sourceField.activeFocus ? window.accent : "#454545"
                                            }
                                        }
                                        AppButton {
                                            text: "Browse…"
                                            primary: !appController.hasBundle
                                            enabled: !appController.isBusy
                                            onClicked: fileDialogController.chooseFolder(
                                                "game",
                                                "Choose a Quest game folder",
                                                appController.folderPath
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
                                            color: appController.hasBundle ? window.textSecondary : "#777777"
                                            font.pixelSize: 10
                                            elide: Text.ElideRight
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
                                Layout.fillWidth: true
                                spacing: 14

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 264
                                    radius: 3
                                    color: window.panel
                                    border.width: 1
                                    border.color: window.line

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 18
                                        spacing: 8
                                        Text {
                                            text: "APP IDENTITY"
                                            color: "#777777"
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 1
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: appController.hasBundle ? appController.sourcePackage : "Current package appears here"
                                            color: appController.hasBundle ? "#b5b5b5" : "#696969"
                                            font.pixelSize: 11
                                            elide: Text.ElideMiddle
                                        }
                                        TextField {
                                            id: packageField
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 42
                                            enabled: appController.hasBundle
                                                     && !appController.isBuilding
                                            text: appController.packageId
                                            placeholderText: "com.dev.studio.game"
                                            color: window.textPrimary
                                            placeholderTextColor: "#5d6a76"
                                            font.pixelSize: 14
                                            selectByMouse: true
                                            leftPadding: 12
                                            rightPadding: 12
                                            onTextEdited: appController.setPackageId(text)
                                            background: Rectangle {
                                                radius: 6
                                                color: "#181818"
                                                border.width: 1
                                                border.color: packageField.activeFocus ? window.accent
                                                              : appController.packageError && appController.hasBundle ? "#8a4d48"
                                                              : "#454545"
                                            }
                                        }
                                        RowLayout {
                                            spacing: 6
                                            AppButton { text: ".mr"; enabled: appController.hasBundle && !appController.isBuilding; onClicked: appController.applyTag("mr") }
                                            AppButton { text: ".dev"; enabled: appController.hasBundle && !appController.isBuilding; onClicked: appController.applyTag("dev") }
                                            AppButton { text: ".test"; enabled: appController.hasBundle && !appController.isBuilding; onClicked: appController.applyTag("test") }
                                            AppButton { text: ".qa"; enabled: appController.hasBundle && !appController.isBuilding; onClicked: appController.applyTag("qa") }
                                            Item { Layout.fillWidth: true }
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: appController.hasBundle
                                                  ? (appController.packageError || "Game name and in-game text stay unchanged.")
                                                  : "A safe suggestion is generated automatically."
                                            color: appController.packageError && appController.hasBundle ? "#d58a84" : "#808080"
                                            font.pixelSize: 10
                                            elide: Text.ElideRight
                                        }
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 1
                                            color: "#353535"
                                        }
                                        Text {
                                            text: "SIGNING LINEAGE"
                                            color: "#777777"
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 1
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: appController.signerLineage
                                            color: appController.hasBundle ? "#a9a9a9" : "#696969"
                                            font.pixelSize: 10
                                            elide: Text.ElideMiddle
                                            ToolTip.visible: lineageMouse.containsMouse
                                            ToolTip.text: text
                                            MouseArea {
                                                id: lineageMouse
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                acceptedButtons: Qt.NoButton
                                            }
                                        }
                                        Item { Layout.fillHeight: true }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 264
                                    radius: 3
                                    color: window.panel
                                    border.width: 1
                                    border.color: window.line

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 14
                                        spacing: 5
                                        Text {
                                            text: "OUTPUT"
                                            color: "#777777"
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 1
                                        }
                                        Text {
                                            text: appController.settings.replaceSourceAfterBuild
                                                  ? "Source replacement path"
                                                  : "Save location"
                                            color: appController.hasBundle ? window.textPrimary : "#6f6f6f"
                                            font.pixelSize: 13
                                            font.weight: Font.Medium
                                        }
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 30
                                            radius: 3
                                            color: outputMouse.containsMouse ? "#282828" : "#232323"
                                            border.width: 1
                                            border.color: outputMouse.containsMouse ? "#505050" : "#383838"
                                            Text {
                                                anchors.left: parent.left
                                                anchors.right: outputChange.left
                                                anchors.verticalCenter: parent.verticalCenter
                                                anchors.leftMargin: 10
                                                anchors.rightMargin: 8
                                                text: appController.hasBundle
                                                      ? appController.outputFolder
                                                      : "Select a game to choose its save location"
                                                color: appController.hasBundle ? window.textSecondary : "#666666"
                                                font.pixelSize: 10
                                                elide: Text.ElideMiddle
                                            }
                                            Text {
                                                id: outputChange
                                                anchors.right: parent.right
                                                anchors.verticalCenter: parent.verticalCenter
                                                anchors.rightMargin: 10
                                                text: appController.settings.replaceSourceAfterBuild
                                                      ? "Source"
                                                      : "Change…"
                                                color: appController.hasBundle ? "#b9b9b9" : "#666666"
                                                font.pixelSize: 10
                                                font.weight: Font.Medium
                                            }
                                            MouseArea {
                                                id: outputMouse
                                                anchors.fill: parent
                                                enabled: appController.hasBundle
                                                         && !appController.isBusy
                                                         && !appController.settings.replaceSourceAfterBuild
                                                hoverEnabled: true
                                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                                onClicked: fileDialogController.chooseFolder(
                                                    "output",
                                                    "Choose where to save the renamed folder",
                                                    appController.outputFolder
                                                )
                                            }
                                        }
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 1
                                            color: "#353535"
                                            Layout.topMargin: 1
                                            Layout.bottomMargin: 1
                                        }
                                        SettingRow {
                                            Layout.fillWidth: true
                                            compact: true
                                            enabled: true
                                            title: "Older firmware patch"
                                            detail: appController.olderFirmwareDetail
                                            checked: appController.settings.olderFirmwarePatch
                                            onChanged: value => appController.setSetting("older_firmware_patch", value)
                                        }
                                        SettingRow {
                                            Layout.fillWidth: true
                                            compact: true
                                            enabled: !appController.isBusy
                                            title: "Replace source after build"
                                            detail: "Verify first, then replace the selected folder"
                                            checked: appController.settings.replaceSourceAfterBuild
                                            onChanged: value => appController.requestReplaceSource(value)
                                        }
                                        SettingRow {
                                            Layout.fillWidth: true
                                            compact: true
                                            enabled: !appController.isBusy
                                            title: "Delete installed folder after success"
                                            detail: "Only after the APK and every OBB are verified on Quest"
                                            checked: appController.settings.deleteSourceAfterInstall
                                            onChanged: value => appController.setSetting("delete_source_after_install", value)
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
                                        color: appController.noticeTone === "error" ? "#d4776f"
                                             : appController.noticeTone === "warning" ? "#d0b15b"
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
                                        text: appController.isInstalling ? "Cancel install"
                                              : appController.canRetryObbs ? "Retry failed OBB transfer"
                                              : appController.buildActionLabel
                                        primary: !appController.isBuilding && !appController.isInstalling
                                        enabled: appController.isInstalling || appController.canRetryObbs
                                                 || appController.isBuilding
                                                 || appController.canBuild
                                                 || appController.buildActionLabel === "Open finished folder"
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
                                Rectangle {
                                    visible: operationPanel.operationActive
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    anchors.leftMargin: 15
                                    anchors.rightMargin: 15
                                    anchors.bottomMargin: 8
                                    height: 8
                                    radius: 4
                                    color: "#303030"
                                    Rectangle {
                                        width: parent.width * Math.max(
                                                   0, Math.min(1, operationPanel.operationProgress)
                                               )
                                        height: parent.height
                                        radius: 4
                                        color: window.accent
                                        Behavior on width { NumberAnimation { duration: 120 } }
                                    }
                                }
                            }
                        }
                    }
                }

                // Library
                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 30
                        anchors.rightMargin: 30
                        anchors.topMargin: 16
                        anchors.bottomMargin: 24
                        spacing: 12

                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    text: libraryController.count === 1
                                          ? "1 saved game"
                                          : libraryController.count + " saved games"
                                    color: window.textPrimary
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: "Select a game below, then choose its newer APK or game folder. Its renamed ID and signing key are reused automatically."
                                    color: window.textSecondary
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                            }
                            AppButton {
                                text: "Open keys"
                                enabled: !appController.isBusy
                                onClicked: libraryController.openKeyFolder()
                            }
                            AppButton {
                                text: "Open Library data"
                                quiet: true
                                enabled: !appController.isBusy
                                onClicked: libraryController.openLibraryFolder()
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 3
                            color: window.panel
                            border.width: 1
                            border.color: window.line

                            Text {
                                visible: libraryController.isEmpty
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 70, 480)
                                text: "No saved games yet\n\nBuild or install a renamed game and it will appear here automatically, ready for future updates."
                                color: window.textSecondary
                                font.pixelSize: 12
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                            }

                            ScrollView {
                                visible: !libraryController.isEmpty
                                anchors.fill: parent
                                anchors.margins: 1
                                contentWidth: availableWidth
                                clip: true

                                ColumnLayout {
                                    width: parent.width
                                    spacing: 0

                                    Repeater {
                                        model: libraryController.rows
                                        delegate: Rectangle {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 102
                                            color: libraryController.selectedId === modelData.id
                                                   ? "#292929"
                                                   : rowMouse.containsMouse ? "#252525" : "transparent"
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
                                                    Layout.preferredWidth: 8
                                                    Layout.preferredHeight: 8
                                                    radius: 4
                                                    color: modelData.keyReady ? "#70b18f" : "#9a8555"
                                                }
                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 5
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
                                                            color: modelData.installed ? "#263b32" : "#343434"
                                                            Text {
                                                                id: libraryStatus
                                                                anchors.centerIn: parent
                                                                text: modelData.status
                                                                color: modelData.installed ? "#78b894" : "#a8a8a8"
                                                                font.pixelSize: 9
                                                                font.weight: Font.DemiBold
                                                            }
                                                        }
                                                    }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: "Original   " + modelData.originalPackage
                                                        color: window.textSecondary
                                                        font.pixelSize: 10
                                                        elide: Text.ElideMiddle
                                                    }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: "Renamed  " + modelData.targetPackage
                                                        color: "#b9b9b9"
                                                        font.pixelSize: 10
                                                        elide: Text.ElideMiddle
                                                    }
                                                }
                                                ColumnLayout {
                                                    spacing: 5
                                                    Text {
                                                        Layout.alignment: Qt.AlignRight
                                                        text: modelData.versionText
                                                        color: window.textSecondary
                                                        font.pixelSize: 10
                                                    }
                                                    Text {
                                                        Layout.alignment: Qt.AlignRight
                                                        text: modelData.keyReady
                                                              ? "Signing key ready"
                                                              : modelData.keyStatus
                                                        color: modelData.keyReady ? "#78b894" : "#d0ad68"
                                                        font.pixelSize: 10
                                                    }
                                                }
                                                AppButton {
                                                    text: "Select"
                                                    primary: libraryController.selectedId === modelData.id
                                                    enabled: !appController.isBusy
                                                    onClicked: libraryController.select(modelData.id)
                                                }
                                            }
                                            MouseArea {
                                                id: rowMouse
                                                anchors.fill: parent
                                                anchors.rightMargin: 92
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: libraryController.select(modelData.id)
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: !libraryController.isEmpty
                            Layout.fillWidth: true
                            Layout.preferredHeight: visible ? 126 : 0
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
                                        text: "UPDATE " + (libraryController.selected.gameName || "SELECTED GAME").toUpperCase()
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Choose a newer APK or a complete game folder. The saved renamed ID and signing key will be applied automatically."
                                        color: window.textPrimary
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Renamed ID  " + (libraryController.selected.targetPackage || "")
                                              + "   •   " + (libraryController.selected.keyStatus || "")
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
                                        enabled: !appController.isBusy
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
                                        enabled: !appController.isBusy
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
                        anchors.leftMargin: 26
                        anchors.rightMargin: 26
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
                                onClicked: fileDialogController.chooseApks(
                                    "bulkApks",
                                    "Add one or more Quest APKs",
                                    appController.folderPath
                                )
                            }
                            AppButton {
                                text: "Add folder…"
                                enabled: !bulkController.isBusy && !appController.isBusy
                                onClicked: fileDialogController.chooseFolder(
                                    "bulkFolder",
                                    "Add a game folder",
                                    appController.folderPath
                                )
                            }
                            AppButton {
                                text: "Scan parent…"
                                enabled: !bulkController.isBusy && !appController.isBusy
                                onClicked: fileDialogController.chooseFolder(
                                    "bulkScan",
                                    "Scan a parent containing game folders",
                                    appController.folderPath
                                )
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 220
                            radius: 3
                            color: bulkDrop.containsDrag ? "#252525" : window.panel
                            border.width: 1
                            border.color: bulkDrop.containsDrag ? window.accent : window.line
                            Behavior on color { ColorAnimation { duration: 100 } }

                            DropArea {
                                id: bulkDrop
                                anchors.fill: parent
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

                                delegate: Rectangle {
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
                                    width: bulkList.width
                                    height: 92
                                    color: index % 2 ? "#202020" : "#222222"

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 16
                                        anchors.rightMargin: 10
                                        spacing: 12
                                        Rectangle {
                                            Layout.preferredWidth: 8
                                            Layout.preferredHeight: 8
                                            radius: 4
                                            color: itemTone === "success" ? "#70b18f"
                                                 : itemTone === "error" ? "#d4776f"
                                                 : itemTone === "warning" ? "#d0b15b"
                                                 : itemTone === "active" ? window.accent
                                                 : "#737373"
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Text {
                                                    text: folderName
                                                    color: window.textPrimary
                                                    font.pixelSize: 13
                                                    font.weight: Font.DemiBold
                                                }
                                                Text {
                                                    text: apkName + "  •  " + obbSummary
                                                    color: "#777777"
                                                    font.pixelSize: 10
                                                    Layout.fillWidth: true
                                                    elide: Text.ElideRight
                                                }
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: currentPackage + "  →  " + targetPackage
                                                color: "#a9a9a9"
                                                font.pixelSize: 11
                                                elide: Text.ElideMiddle
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: itemDetail
                                                color: "#777777"
                                                font.pixelSize: 10
                                                elide: Text.ElideRight
                                            }
                                        }
                                        Rectangle {
                                            Layout.preferredWidth: statusText.implicitWidth + 18
                                            Layout.preferredHeight: 26
                                            radius: 13
                                            color: itemTone === "success" ? "#263c32"
                                                 : itemTone === "error" ? "#482b29"
                                                 : itemTone === "warning" ? "#443b25"
                                                 : "#303030"
                                            Text {
                                                id: statusText
                                                anchors.centerIn: parent
                                                text: itemStatus
                                                color: "#d0d0d0"
                                                font.pixelSize: 10
                                                font.weight: Font.Medium
                                            }
                                        }
                                        AppButton {
                                            text: "Remove"
                                            quiet: true
                                            enabled: !bulkController.isBusy
                                            onClicked: bulkController.removeItem(index)
                                        }
                                    }
                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        height: itemProgress > 0 && itemProgress < 1 ? 2 : 0
                                        color: "#303030"
                                        Rectangle {
                                            width: parent.width * itemProgress
                                            height: parent.height
                                            color: window.accent
                                            Behavior on width { NumberAnimation { duration: 100 } }
                                        }
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
                                    Layout.minimumWidth: 260
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
                                        background: Rectangle { color: "#1b1b1b"; border.width: 1; border.color: bulkController.suffixError ? "#7b4641" : "#414141"; radius: 3 }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: bulkController.suffixError || "Example: com.studio.game + a → com.studio.gamea"
                                        color: bulkController.suffixError ? "#d58a83" : "#777777"
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                }
                                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: window.line }
                                ColumnLayout {
                                    Layout.minimumWidth: 430
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
                                text: "Clear"
                                enabled: !bulkController.isBusy && bulkController.count > 0
                                onClicked: bulkController.clear()
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: bulkController.isBusy ? 2 : 0
                            color: "#303030"
                            Rectangle {
                                width: parent.width * bulkController.progress
                                height: parent.height
                                color: window.accent
                                Behavior on width { NumberAnimation { duration: 120 } }
                            }
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
                }

                // Settings page
                Item {
                    ScrollView {
                        anchors.fill: parent
                        contentWidth: availableWidth
                        clip: true

                        ColumnLayout {
                            width: parent.width
                            spacing: 18
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.leftMargin: 30
                            anchors.rightMargin: 30
                            anchors.topMargin: 16
                            anchors.bottomMargin: 28

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 211
                                radius: 3
                                color: window.panel
                                border.width: 1
                                border.color: window.line
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "ANDROID TOOLS"
                                            color: "#777777"
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 1
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: toolController.allReady ? "READY" : "NEEDS ATTENTION"
                                            color: toolController.allReady ? "#78b894" : "#d0ad68"
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
                                                     : modelData.status === "damaged" ? "#d4776f"
                                                     : "#d0b15b"
                                            }
                                            Text {
                                                text: modelData.label + " " + modelData.version
                                                color: window.textPrimary
                                                font.pixelSize: 12
                                                font.weight: Font.Medium
                                            }
                                            Item { Layout.fillWidth: true }
                                            Text {
                                                text: modelData.detail
                                                color: window.textSecondary
                                                font.pixelSize: 11
                                            }
                                        }
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: toolController.isBusy ? 2 : 1
                                        color: "#333333"
                                        Rectangle {
                                            width: parent.width * toolController.progress
                                            height: parent.height
                                            color: window.accent
                                            Behavior on width { NumberAnimation { duration: 120 } }
                                        }
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
                                                color: toolController.tone === "error" ? "#d98a82"
                                                     : toolController.tone === "success" ? "#78b894"
                                                     : toolController.tone === "warning" ? "#d0ad68"
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
                                            onClicked: toolController.runAction()
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 236
                                radius: 3
                                color: window.panel
                                border.width: 1
                                border.color: window.line
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 0
                                    Text {
                                        text: "BUILD DEFAULTS"
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
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
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 116
                                radius: 3
                                color: window.panel
                                border.width: 1
                                border.color: window.line
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 16
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Text {
                                            text: "OLD OUTPUT CLEANUP"
                                            color: "#777777"
                                            font.pixelSize: 9
                                            font.weight: Font.DemiBold
                                            font.letterSpacing: 1
                                        }
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

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 238
                                radius: 3
                                color: window.panel
                                border.width: 1
                                border.color: window.line
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 0
                                    Text {
                                        text: "APP"
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
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
                                                 : updateController.tone === "warning" ? "#d0ad68"
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

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 206
                                radius: 3
                                color: window.panel
                                border.width: 1
                                border.color: window.line
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8
                                    Text {
                                        text: "SIGNING IDENTITY"
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: appController.signingStatus
                                        color: "#a5a5a5"
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        text: "DEFAULT BACKUP LOCATION"
                                        color: "#777777"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 1
                                        Layout.topMargin: 3
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 32
                                            radius: 3
                                            color: defaultBackupMouse.containsMouse ? "#282828" : "#232323"
                                            border.width: 1
                                            border.color: defaultBackupMouse.containsMouse ? "#505050" : "#383838"
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
