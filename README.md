<p align="center">
  <img src="assets/quest-apk-renamer.png" width="92" alt="Quest APK Renamer icon">
</p>

<h1 align="center">Quest APK Renamer</h1>

<p align="center">
  Make a separately installable copy of a Meta Quest app by changing its
  Android package ID. The APK, OBB files, and manifest stay together.
</p>

<p align="center">
  <a href="#download">Download</a> ·
  <a href="#getting-started">Getting started</a> ·
  <a href="#troubleshooting">Troubleshooting</a> ·
  <a href="#building-from-source">Build from source</a>
</p>

<p align="center">
  <img alt="Version 1.9.0" src="https://img.shields.io/badge/version-1.9.0-6f5ef7">
  <img alt="Windows, macOS, and Linux" src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-26334d">
  <img alt="MIT License" src="https://img.shields.io/badge/license-MIT-2ea44f">
</p>

> [!IMPORTANT]
> Only modify software you own or have permission to use. Renaming a package
> does not bypass licensing, entitlement, anti-tamper, or online checks.

![Quest APK Renamer main window](docs/screenshots/main-window.png)

## What it does

Pick a Quest game folder and Quest APK Renamer will:

- find its APK, OBB files, manifest, package ID, and version;
- suggest a valid new package ID;
- check the bundle, Android tools, and available storage;
- rebuild, sign, and verify the renamed APK;
- rename the OBB files and update `release.manifest`;
- create readable text and JSON reports; and
- install and verify the finished bundle over USB.

The original folder is left alone by default. Everything runs locally, and the
release packages already include the Android tools and Java runtime they need.

The app also includes an APK inspector, bulk processing, safe cancellation,
failed-OBB retry, signing-key backups, and a persistent activity log.

## Download

Open the [1.9.0 beta release](../../releases/tag/v1.9.0-beta.1) and download the
package for your computer:

| Platform | File |
| --- | --- |
| Windows | `Quest-APK-Renamer-1.9.0-Setup.exe` |
| Apple Silicon Mac | `Quest-APK-Renamer-1.9.0-macOS-arm64.dmg` |
| Intel Mac | `Quest-APK-Renamer-1.9.0-macOS-x86_64.dmg` |
| Linux x86_64 | `Quest-APK-Renamer-1.9.0-Linux-x86_64.tar.gz` |

On Linux, extract the archive and run `./install.sh`.

Windows builds are not currently code-signed, and macOS builds are not
notarized, so your system may show an unknown-developer warning. You can verify
your download against the matching `SHA256SUMS` file before opening it.

## Getting started

1. Connect your Quest with a data-capable USB cable.
2. Approve the USB debugging prompt inside the headset and keep it awake.
3. Choose or drop the game's main folder into Quest APK Renamer.
4. Accept the suggested app ID or enter your own.
5. Wait for **Ready to build**, then select **Create renamed game**.
6. Select **Install finished game** when the build completes.

Android sees the new package ID as a separate app. It gets its own save-data
location and does not replace the original installation.

### Expected folder layout

A typical source folder looks like this:

```text
My Game/
├── com.example.game.apk
├── release.manifest
└── com.example.game/
    └── main.11868.com.example.game.obb
```

By default, the finished copy is created beside it:

```text
My Game - Renamed/
├── com.example.gamea.apk
├── release.manifest
├── RENAMED-BUNDLE.txt
├── RENAME-REPORT.txt
├── RENAME-REPORT.json
└── com.example.gamea/
    └── main.11868.com.example.gamea.obb
```

## Useful tools

**APK analysis** shows SDK levels, CPU architectures, permissions, components,
hashes, signatures, certificates, and the package references that will change.

**Bulk tools** can queue several folders, preview their new IDs, and build or
install them one at a time. One failed item does not stop the rest of the queue.

**Options & tools** contains less common settings, including custom output
folders, source replacement, cleanup, Android-tool repair, signing-key backup,
update checks, and debug-log export.

![APK analysis and rename preview](docs/screenshots/apk-analysis.png)

## Compatibility

Most package references can be updated safely, but no renaming tool can support
every app. A game may still depend on its original ID in native code, encrypted
data, server configuration, licensing, or anti-tamper checks. In those cases it
may install but fail to launch or connect.

Quest APK Renamer reports what it changed and deliberately leaves risky
references in compiled assets or native libraries untouched.

## Keep your signing key safe

The first signed build creates a local signing identity. Back up these two files
together and keep them private:

```text
quest-renamer-signing-key.jks
signing-key.json
```

They are stored in:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Quest APK Renamer\` |
| macOS | `~/Library/Application Support/Quest APK Renamer/` |
| Linux | `~/.local/share/quest-apk-renamer/` |

Android requires the same key to update an installed renamed app. If the key is
lost, you will need to uninstall that app before installing a build signed with
a different one.

## Troubleshooting

### Quest is not detected

- Make sure Developer Mode and USB debugging are enabled.
- Approve the computer inside the headset.
- Try another data-capable USB cable or port.
- Keep the headset awake and close other apps that may be using ADB.
- Select the Quest status card to refresh the connection.

### The app installs but cannot find its game data

The OBB must be stored at:

```text
/sdcard/Android/obb/<new.package>/
```

The APK package ID, OBB folder, and package part of the OBB filename must match
exactly. If only a transfer failed, use **Retry only the failed OBB files**.

### Android reports a signature conflict

Restore the signing-key backup used for that renamed package, or uninstall the
existing renamed app before installing a build signed with a different key.

### Something else went wrong

Open **Activity log** first, then use **Options & tools → Open debug log** for
more detail. The log may contain local file paths, so review it before sharing.

You can also [open an issue](https://github.com/RockoTheeHut/Quest-APK-Renamer/issues/new/choose).
Include your operating system, app version, what you selected, and the relevant
log text. Do not upload copyrighted APKs, OBBs, or signing keys.

## Building from source

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```

Build a release package:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1 -BuildInstaller
```

```bash
# macOS
./macos/build.sh

# Linux x86_64
./linux/build.sh
```

Platform-specific instructions are in
[windows/README.md](windows/README.md),
[macos/README.md](macos/README.md), and
[linux/README.md](linux/README.md). Release maintainers should also read
[docs/RELEASING.md](docs/RELEASING.md).

## Privacy, security, and licenses

Game files are processed locally and are never uploaded. Source replacement is
optional and rollback-protected, signing passwords are hidden from logs, and
managed cleanup is limited to output created by the app. Optional update checks
contact GitHub's public release API.

See [SECURITY.md](SECURITY.md) for security reporting,
[CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines, and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled component licenses.

Quest APK Renamer is released under the [MIT License](LICENSE).
