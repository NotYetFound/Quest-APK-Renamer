<p align="center">
  <img src="assets/quest-apk-renamer.png" width="96" alt="Quest APK Renamer icon">
</p>

<h1 align="center">Quest APK Renamer</h1>

<p align="center">
  Rename a Quest app's Android package ID, rebuild and sign its APK, match its
  OBB files, and install the finished bundle—all from one desktop app.
</p>

<p align="center">
  <img alt="Version 1.8.0" src="https://img.shields.io/badge/version-1.8.0-7c5cff">
  <img alt="Windows, macOS, and Linux" src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-273247">
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/Python-3.10%2B-3776ab">
  <img alt="MIT License" src="https://img.shields.io/badge/license-MIT-2ea44f">
</p>

> [!IMPORTANT]
> Use Quest APK Renamer only with software you own or are authorized to modify.
> It does not bypass store ownership, licensing, online entitlement, or
> anti-tamper systems.

> [!WARNING]
> This app was made 100% by AI, so expect some bugs and use caution. Keep
> backups of your original bundles and signing keys.

![Quest APK Renamer main window](docs/screenshots/main-window.png)

## What it does

Quest APK Renamer is a local, non-destructive tool for Quest/Android game
folders containing an APK, optional OBB files, and an optional
`release.manifest`.

- Drop a complete game folder onto the app or choose it with the native folder
  picker.
- Detect the current package ID and version automatically.
- Change the technical Android package ID without changing the game name or
  in-game text.
- Rebuild, zip-align, sign, and verify the APK with your persistent local key.
- Rename every OBB to match the new package ID.
- Update the accompanying `release.manifest`.
- Check files, tools, package rules, disk space, and Quest storage
  automatically.
- Install the APK and OBB together over USB.
- Verify the installed package and transferred OBB sizes.
- Retry only failed OBB transfers.
- Cancel at safe stage boundaries and choose whether partial files are removed.
- Rename or install several selected folders sequentially, with a final
  success/failure overview.
- Optionally replace a source folder using a completed staging build with
  rollback protection.
- Optionally move a local renamed folder to Trash only after its Quest install
  is fully verified.
- Move old app-created output folders to Trash or the Windows Recycle Bin.

By default, the original APK, OBB, manifest, and source folder are never
modified. The explicit **Replace source** option builds a complete staging
folder first and only swaps it into place after success; the original is moved
to recoverable Trash.

## Download

### Windows

Open this repository's [latest release](../../releases/latest) and download:

```text
Quest-APK-Renamer-1.8.0-Setup.exe
```

The installer is per-user, needs no administrator access, and includes Java,
ADB, Apktool, the APK signer, and drag-and-drop support.

Early builds are not code-signed. Windows SmartScreen may show an
**Unknown publisher** warning. Verify the downloaded file against
`SHA256SUMS-Windows.txt` on the release before running it.

### macOS

Download the DMG matching your Mac:

```text
Quest-APK-Renamer-1.8.0-macOS-arm64.dmg
Quest-APK-Renamer-1.8.0-macOS-x86_64.dmg
```

Choose `arm64` for Apple Silicon (M1 or newer) and `x86_64` for Intel. Open the
DMG and drag **Quest APK Renamer** into Applications. The app includes Java,
ADB, Apktool, the APK signer, and native drag-and-drop support.

Ad-hoc-signed development builds trigger a Gatekeeper warning. A release
signed with an Apple Developer ID and notarized by Apple opens normally.
Verify the DMG against its matching `SHA256SUMS-macOS-*.txt` file.

### Linux

Download:

```text
Quest-APK-Renamer-1.8.0-Linux-x86_64.tar.gz
```

Extract it, open a terminal inside the extracted folder, and run:

```bash
./install.sh
```

The portable bundle includes Python/Tk, Java with `keytool`, ADB, Apktool, the
signer, and native drag-and-drop support. Installation is per-user, needs no
administrator access, and adds Quest APK Renamer to the app launcher. You can
also run the bundled **Quest APK Renamer** executable directly.

The prebuilt Linux package currently supports x86_64. Other Linux
architectures can run from source. Verify the archive against
`SHA256SUMS-Linux-x86_64.txt`.

## Quick start

1. Connect the Quest with USB debugging enabled, approve the computer inside
   the headset, and keep the headset awake.
2. Choose or drop the folder containing the APK, `release.manifest`, and OBB
   subfolder.
3. Keep the suggested new ID, or edit it if you want.
4. Wait for the green **Ready to build** pill, then select
   **Create renamed game**.
5. When the build finishes, select **Install current folder**.

A changed package ID makes Android treat the result as a separate app. The new
app uses its own save-data location and does not replace the original package.

## Expected input

The folder can look like this:

```text
My Game/
├── com.example.game.apk
├── release.manifest
└── com.example.game/
    └── main.11868.com.example.game.obb
```

The output is created in a new sibling folder and looks like:

```text
My Game - Renamed/
├── com.example.game.renamed.apk
├── release.manifest
├── RENAMED-BUNDLE.txt
└── com.example.game.renamed/
    └── main.11868.com.example.game.renamed.obb
```

## Advanced controls

![Quest APK Renamer advanced options and details](docs/screenshots/advanced-options.png)

**More options** provides:

- a custom output location;
- APK-only selection for unusual folder layouts;
- compact OBB, signing, backup-reminder, replacement, and cleanup switches;
- Android tool repair and verification;
- signing-key backup;
- a persistent switch for automatic signing-key backup questions;
- staged source-folder replacement;
- verified-install-only local cleanup;
- managed-output cleanup; and
- the detailed operation log.

## Bulk rename and install

Use **Bulk tools** in the main window or drop several game folders onto the
main window.

The bulk window lets you:

- select several APK files in one picker;
- add individual folders;
- scan the direct children of a parent folder;
- preview every current and resulting package ID;
- choose a suffix such as `a`, producing
  `com.example.gamea` from `com.example.game`;
- rename every folder one at a time;
- install every folder one at a time; and
- review a per-folder success/failure overview at the end.

Source replacement and post-install local cleanup are separate opt-in switches.
A failed rename leaves its original untouched. A failed or partially verified
install keeps its local folder.

![Quest APK Renamer bulk tools](docs/screenshots/bulk-tools.png)

## Installing on Quest

The app performs the installation in this order:

1. Detect exactly one authorized Quest through ADB.
2. Check available headset storage.
3. Warn if the new package ID already exists.
4. Install or update the APK.
5. Create `/sdcard/Android/obb/<new.package>/`.
6. Copy and size-check every OBB.
7. Confirm that Android reports the new package as installed.

If an OBB transfer fails, use **Retry failed OBB**. The APK is not reinstalled,
and successful OBB files are not resent.

## Signing key: back it up

The first signed build creates a persistent signing identity:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Quest APK Renamer\` |
| macOS | `~/Library/Application Support/Quest APK Renamer/` |
| Linux | `~/.local/share/quest-apk-renamer/` |

Back up `quest-renamer-signing-key.jks` and `signing-key.json` together and keep
them private. Android requires the same key to install future updates over an
existing renamed package. Losing the key means that package must be uninstalled
before a differently signed build can be installed.

The Windows uninstaller intentionally preserves this folder.

Turn off **Ask me to back up signing keys after builds** under **More options**
if you do not want the automatic question. The preference persists across
restarts and never disables the manual **Back up signing key…** button.

## Troubleshooting

### Quest not connected

- Enable Developer Mode for the headset.
- Enable USB debugging and approve the computer inside the headset.
- Try a data-capable USB cable and keep the Quest awake.
- Close other tools that may be controlling ADB, then refresh the status card.

### App launches slowly or stays on the loading screen

Some games store the original package ID in native code, encrypted data,
server configuration, or anti-tamper checks. Package renaming cannot safely
rewrite those unknown references. Review **Show details** for the last completed
stage.

### Installation succeeds but game data is missing

Confirm that the renamed OBB is under:

```text
/sdcard/Android/obb/<new.package>/
```

The folder name, APK package ID, and package portion of the OBB filename must
match exactly.

### Update reports a signature conflict

Use the same signing-key backup used for the installed renamed package, or
uninstall that renamed package before installing a build signed with another
key.

## Build and test

Run the shared tests:

```bash
python3 -m unittest discover -s tests -v
```

Build the Windows portable app and installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1 -BuildInstaller
```

Build the macOS app and architecture-specific DMG on a Mac:

```bash
./macos/build.sh
```

Build the self-contained Linux x86_64 package:

```bash
./linux/build.sh
```

See [windows/README.md](windows/README.md),
[macos/README.md](macos/README.md), and [linux/README.md](linux/README.md) for
platform build details, and
[docs/RELEASING.md](docs/RELEASING.md) for the complete release checklist.

## Project status

Version 1.8.0 includes staged source replacement, verified-install-only local
cleanup, sequential bulk rename/install queues, and Windows/macOS/Linux
packaging.

Platform testing is still limited:

- **Windows:** partially tested by hand. Automated tests and release packaging
  pass, and the Setup and portable builds should work.
- **macOS:** not yet tested by hand. Automated Apple Silicon and Intel builds
  pass, and both DMGs should work, but real-device feedback is especially
  helpful.

If you have any problems, please
[open an issue](https://github.com/RockoTheeHut/Quest-APK-Renamer/issues/new/choose).
I will investigate and fix it as soon as I can. Release artifacts still need
hands-on smoke tests on their matching operating systems before a public
release is marked stable.

## Privacy and safety

- Everything runs locally; APKs and OBBs are not uploaded.
- Source bundles are read-only by default. Opt-in replacement is staged and
  rollback-protected.
- Cleanup accepts only output folders carrying the app's managed-output marker.
- Tool downloads are pinned and SHA-256 verified where applicable.
- Release downloads include platform-specific SHA-256 checksum files.
- Signing passwords are masked from the operation log.

See [SECURITY.md](SECURITY.md) for private vulnerability reporting guidance.

## Contributing

Bug reports and focused pull requests are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes. Do not attach
copyrighted APKs, OBB files, signing keys, or other private game data to issues.

## Third-party components

Quest APK Renamer packages or integrates Apktool, Uber APK Signer,
TkinterDnD2/tkdnd, Android SDK Platform-Tools, and Eclipse Temurin.
Versions, sources, and licensing notes are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

Quest APK Renamer is available under the [MIT License](LICENSE). Bundled
third-party components remain under their own licenses.
