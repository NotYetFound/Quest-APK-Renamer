# Quest APK Renamer

[![Latest release](https://img.shields.io/github/v/release/RockoTheeHut/Quest-APK-Renamer?display_name=tag&sort=semver)](https://github.com/RockoTheeHut/Quest-APK-Renamer/releases/latest)
[![Tests](https://github.com/RockoTheeHut/Quest-APK-Renamer/actions/workflows/test.yml/badge.svg)](https://github.com/RockoTheeHut/Quest-APK-Renamer/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Rename, rebuild, sign, inspect, and install authorized Meta Quest APK/OBB test bundles from one
desktop app. Quest APK Renamer keeps the game name and in-game text unchanged while giving the
copy a separate Android package ID.

![Quest APK Renamer dashboard](docs/screenshots/dashboard.png)

## Download

Get the current stable build from the
[GitHub Releases page](https://github.com/RockoTheeHut/Quest-APK-Renamer/releases/latest).

| Platform | Recommended download | Alternative |
| --- | --- | --- |
| Windows 10/11 x64 | `Quest-APK-Renamer-1.4.0-Setup.exe` | Portable ZIP |
| Linux x86_64 | AppImage | Portable tarball with launcher installer |
| Apple Silicon macOS | `macOS-arm64.dmg` | — |
| Intel macOS | `macOS-x86_64.dmg` | — |

GitHub shows a copyable SHA-256 digest beside each release download. The Windows package is not
Authenticode-signed, and the macOS packages are not currently notarized, so the operating system
may show an unknown-developer warning.

## Quick start

1. Choose a folder containing an APK and its optional OBB folder, or choose one APK directly.
2. Review the suggested package ID and change it if needed.
3. Select **Build renamed copy**.
4. Connect and authorize your Quest, then install the completed APK and OBB files together.

The original folder is left untouched unless **Replace source after build** is explicitly enabled.
If **Delete installed folder after success** is enabled, cleanup happens only after the APK and
every OBB have been verified on the headset.

## What it handles

- Rewrites the Android package ID and matching technical references.
- Rebuilds, signs, and verifies the finished APK with a persistent local identity.
- Renames matching OBB directories/files and regenerates `release.manifest`.
- Optionally applies the pinned older-firmware compatibility patch when the APK already contains
  the supported ARM64 loader.
- Installs the APK and every OBB as one guided job, with Quest storage checks first.
- Verifies the installed package and remote OBB sizes.
- Produces readable text and JSON reports for every successful build.

## Main features

### Guided dashboard

The dashboard analyzes the selected bundle automatically, suggests a safe separate app ID, shows
the current signing lineage, checks tools and disk space, and explains what is needed before the
build button unlocks. Folders and individual APKs can also be dropped directly onto the window.

Quick ID presets include `.mr`, `.dev`, `.test`, and `.qa`. Output normally goes into a sibling
folder ending in ` - Renamed`.

### Bulk rename and install

![Bulk rename and install queue](docs/screenshots/bulk-queue.png)

Add several APKs or game folders, scan a parent folder, preview one package-ID suffix across the
queue, and process each game sequentially. One failure does not stop later games, cancellation
waits for a safe boundary, and the final overview shows each success or failure.

### APK Inspector

![APK Inspector overview](docs/screenshots/apk-inspector.png)

The separate inspector performs an opt-in full decode without changing the APK. It reports:

- app, version, SDK, ABI, locale, component, and file-hash details;
- signature schemes, certificates, recognized signer, and embedded signer lineage;
- permissions and hardware/software features;
- exact package-reference changes a rename would make; and
- native or compiled references that are reported but deliberately preserved.

Inspection can be cancelled safely and exported as JSON.

### Device-aware installation

Quest status and available storage stay visible without blocking the interface. The app handles
disconnected, unauthorized, offline, multiple-device, missing-ADB, and Linux USB-permission states.
Before installation it checks whether the package already exists and warns about signing conflicts.

If only an OBB transfer fails, it can be retried without reinstalling the APK. Progress shows the
current stage and a real percentage, and cancellation waits until the current safe APK/OBB boundary.

### Settings and Android tools

![Settings and verified Android tools](docs/screenshots/settings.png)

Release packages include a trimmed Java runtime, ADB, pinned Apktool, Uber APK Signer, and the
optional older-firmware compatibility asset. Missing or damaged pinned tools can be repaired from
Settings and are verified before atomic replacement.

The older-firmware option replaces an existing ARM64 `libovrplatformloader.so` with the pinned
[Event Horizon](https://github.com/veygax/eventhorizon) compatibility loader. It never inserts the
loader into an APK that did not already contain that file.

### Signing identity and safe recovery

- One persistent signing identity is reused so renamed apps can receive later updates.
- Existing legacy Quest APK Renamer signing material is validated and migrated automatically.
- Backup and restore operations are integrity-checked and activated atomically.
- Recognized original signers can be recorded in the new certificate lineage.
- Interrupted builds are detected on the next launch and can be opened, kept, or removed.
- App-created old outputs can be moved to the operating-system Trash after a report safety check.

### Developer-friendly logs

The standalone Logs window shows the current session and keeps a rotating 5 MB log with UTC
timestamps, build stages, shell-free tool commands, and complete Apktool, signer, and ADB output.
Secrets are redacted. **Copy support info** collects app, OS, device, tool, and recent-log details
into one readable block for an issue report.

## Complete feature reference

The sections above describe the main workflow. This reference lists the remaining user-facing
capabilities so features do not disappear into release notes or menus.

### Input and navigation

- Select a game folder, paste its path, choose one exact APK, or drag and drop either one.
- Install the app's latest completed build or select any existing finished APK/OBB folder.
- Open or change the automatic output location directly from the dashboard.
- Dedicated Dashboard, Bulk Queue, APK Inspector, Settings, and standalone Logs views.
- Responsive scrolling, subtle state transitions, visible keyboard focus, and safe default focus
  in destructive confirmations.
- `Ctrl+1`–`Ctrl+4` switch pages, `Ctrl+O` opens the game picker, and `Ctrl+L` opens Logs.

### APK, OBB, and manifest processing

- Automatic package, version, SDK, ABI, permission, signer, and bundle-size analysis.
- Safe package-ID suggestion plus `.mr`, `.dev`, `.test`, and `.qa` presets.
- Full APK decode, technical package-reference rewrite, rebuild, persistent signing, signature
  verification, and optional OBB-copy/signing switches in Settings.
- Matching OBB directory/filename changes and `release.manifest` regeneration.
- Atomic output publishing into a sibling ` - Renamed` folder or a chosen destination.
- `RENAMED-BUNDLE.txt`, human-readable `RENAME-REPORT.txt`, and structured
  `RENAME-REPORT.json` output with source/output signing provenance.
- Optional, checksum-pinned Event Horizon older-firmware loader replacement, only when the
  compatible ARM64 file already exists in the source APK.
- Patch-only rebuild/sign mode when the package ID is unchanged; compatibility availability is
  detected automatically and the action changes to **Apply older-firmware patch**.

### Automatic checks, progress, and recovery

- Optional automatic preflight checks for input readability, package rules, Android tools, output
  safety, local free space, existing Quest packages, and Quest free space.
- Finished-size estimates before building and aggregate local/Quest-space warnings for bulk jobs.
- Weighted build progress, byte-based OBB transfer progress, real percentages, and the current
  operation stage.
- Safe cancellation between build stages and OBB files, followed by a choice to keep or remove
  app-created partial output.
- Crash-persistent staging recovery with guarded **Open**, **Keep**, and **Remove** choices on the
  next launch.

### Quest installation

- Non-blocking headset model, authorization state, ADB state, and available-storage reporting.
- Clear states for disconnected, unauthorized, offline, multiple devices, missing ADB, and Linux
  USB/udev permission problems.
- Existing-package warning before an update attempt, including the signing-key conflict risk.
- Sequential APK and OBB installation, installed-package verification, and remote OBB-size
  verification.
- Retry only failed OBB transfers without reinstalling the APK.
- Install progress, safe cancellation, contextual failure reports, and direct access to logs.

### Output and cleanup controls

- Rollback-protected **Replace source after build** mode: build and verify first, swap atomically,
  then move the unedited source to the operating-system Trash.
- **Delete installed folder after success** mode, which runs only after the APK and every OBB are
  verified on Quest.
- The two controls can be enabled independently or together in both single and bulk workflows.
- Report-verified cleanup for old app-created outputs, with the exact target shown before
  Trash/Recycle Bin removal.
- Original and failed-install folders are preserved whenever verification or safe cleanup fails.

### Signing identity and lineage

- Persistent local signing identity reused for compatible updates to renamed apps.
- Optional signing-key backup reminder plus manual integrity-checked backup and atomic restore.
- Existing legacy signing-key migration with validation and preservation of the original files.
- Known-signer recognition based only on certificate `CN` and `O` values.
- Embedded `Previously signed by …` provenance, cached per-lineage signing identities, and backups
  that include every generated lineage key.
- Seed recognition for Quest APK Renamer, APC, VRP, NIF, vrSrc, Meta/Oculus, Android Debug, and
  Google identities.

### Bulk workflow

- Multi-select APK picker, individual folder picker, multi-folder drag and drop, and direct-child
  parent-folder scanning.
- Duplicate and nested selection rejection plus a preview of one suffix across every package ID.
- Sequential build and install queues with per-game progress and safe stage boundaries.
- Failure isolation so later games continue, followed by a complete success/failure overview.
- Bulk source replacement and verified post-install cleanup with the same safeguards as Dashboard.

### Inspector, tools, updates, and support

- Full APK Inspector metadata, hashes, signature schemes/certificates, signer lineage,
  permissions/features, technical rename preview, preserved native-reference warnings,
  cancellation, and atomic JSON export.
- Exact pinned Android-tool versions and integrity state in Settings.
- Cancellable repair of missing or damaged Apktool, signer, and compatibility files, with
  checksum verification, atomic replacement, and activation without restarting.
- Optional background update checks, an explicit **Check now** action, stable/prerelease-aware
  version ordering, legacy-tag handling, and a dismissible release banner.
- Persistent 5 MB rotating log, readable operation headings, full external-tool output,
  secret-value redaction, current-session filtering, open/save/clear actions, and one-click
  support information.
- Direct actions to open the app-data folder, current log, completed output, failure report, and
  relevant release page in the operating system's normal desktop app.
- Linux application-menu integration, Windows Start Menu installation, portable Windows/Linux
  builds, AppImage, and native Intel/Apple Silicon macOS packages.

## Cross-platform file selection

Every Browse action uses the same fallback chain:

- Windows and macOS try the operating system's native dialog first.
- Linux prefers `kdialog` on KDE/Plasma and `zenity` on GNOME-family desktops.
- Qt's cross-platform dialog is the next fallback.
- Tk is retained only as the final compatibility option.

Cancelling a working picker does not cause another picker to appear. If selection fails on a Linux
distribution or desktop environment, please open an issue and include the requested DE information.

## Platform notes

All release packages are built on their matching operating system in GitHub Actions. Linux and
Windows have hands-on testing; macOS has more limited real-hardware coverage. If something fails,
please [open an issue](https://github.com/RockoTheeHut/Quest-APK-Renamer/issues/new/choose)—reports
from less common Linux distributions and desktop environments are especially useful.

### macOS first launch

Until the DMGs are Developer ID signed and notarized, macOS may block the first launch. In Finder,
Control-click **Quest APK Renamer**, choose **Open**, and confirm the prompt. Do not bypass warnings
for a download obtained from anywhere other than this repository.

### Linux USB access

Developer Mode and USB debugging must be enabled on the Quest, and the authorization prompt inside
the headset must be accepted. Some distributions also require an Android/Meta udev rule before ADB
can access the device; the app shows Linux-specific guidance when it detects this state.

## Safety and scope

Use Quest APK Renamer only with applications you own or are authorized to modify. It does not bypass
entitlements, accounts, licensing, or platform security. Re-signing changes the APK certificate, so
Android cannot update an installed copy signed by a different key.

Keep a private backup of the signing identity before relying on renamed packages for long-term
testing. Review local paths and package information before sharing logs or reports publicly.

## Run from source

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
quest-renamer
```

On Windows, activate the environment with `.venv\Scripts\activate` instead. A source checkout needs
compatible Java/ADB tools; normal release downloads already contain the supported toolchain.

Run the same checks used by CI:

```bash
pytest -q
ruff check src tests scripts
mypy src
QT_QPA_PLATFORM=offscreen quest-renamer --smoke-test
```

## Project structure

```text
src/quest_renamer/
├── domain/          Pure models, validation, and workflow rules
├── services/        Build, install, device, and platform contracts
├── infrastructure/  Filesystem, Android-tool, ADB, and OS implementations
├── presentation/    QML-facing controllers and asynchronous view state
├── qml/             Qt Quick interface
└── assets/          Application-owned resources
```

The domain and service layers do not depend on Qt. Long-running APK, ADB, update, and repair work
runs outside the interface thread.

- [Architecture](docs/ARCHITECTURE.md)
- [Packaging](docs/PACKAGING.md)
- [Release checklist](docs/RELEASING.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

Quest APK Renamer is released under the [MIT License](LICENSE).
