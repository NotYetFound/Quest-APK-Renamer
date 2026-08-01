# Quest APK Renamer

> Current release-candidate version: **1.4.0**.

Quest APK Renamer is a guided desktop utility for creating, inspecting, and installing separate
authorized Meta Quest APK/OBB test bundles. Version 1.4 replaces the legacy interface with the
maintainable Qt Quick architecture described below.

> This app was made 100% with AI assistance, so expect bugs, keep backups, and use it with care.

## Direction

- **QML / Qt Quick interface** for a responsive, polished desktop experience.
- **Python engine** for APK inspection, rebuilding, signing, ADB, and safe file operations.
- **Typed workflows** instead of UI methods directly running tools.
- **Platform adapters** for Windows, macOS, and Linux behavior.
- **Testable services** so build and install behavior can be verified without a headset.

The current foundation includes the neutral dashboard, bundle selection, package-ID workspace,
separate bulk and settings pages, drag and drop, persistent cross-platform settings, bounded
activity logs in a dedicated standalone window, and non-blocking Quest/ADB status with free-space
reporting. The single-game
workflow now analyzes APKs, runs automatic readiness checks, rebuilds and signs in an isolated
staging area, renames OBB data, and publishes the finished folder atomically.

The complete build path decodes the APK, rewrites Android package references, rebuilds it,
signs it with the persistent local identity, verifies that signature, renames OBB directories and
filenames to the new package ID, and regenerates `release.manifest`. Each finished folder includes
`RENAMED-BUNDLE.txt`, a readable `RENAME-REPORT.txt`, and the complete machine-readable
`RENAME-REPORT.json` for debugging and automation.

If the source APK has a recognized signer, the new certificate records that provenance in its
`L=Previously signed by …` field. Recognition deliberately checks only certificate `CN` and `O`
fields, so a rename tag or embedded lineage cannot create a false match. Each full lineage identity
is cached and reused for future updates, and signing-key backups include every lineage key. The
seed registry recognizes Quest APK Renamer, APC, VRP, NIF, vrSrc, Meta/Oculus, Android Debug, and
Google identities.

Finished folders can be installed from either dashboard install button. Installation always
handles the APK and every detected OBB as one job, checks available Quest storage first, verifies
remote OBB sizes, and confirms the installed package. Failed OBB transfers can be retried without
reinstalling the APK. Cancellation waits for a safe file boundary. An optional cleanup setting
moves the finished local folder to Trash only after the APK and every OBB are verified on Quest.

Source replacement is a separate opt-in output mode. The app builds the complete result in a
sibling staging folder, verifies it, swaps it into the original folder path with automatic
rollback, and then moves the unedited folder to the operating-system Trash. If Trash is
unavailable, the original is kept as a visible backup instead. Source replacement and
post-install cleanup can be enabled together: in that case, the replaced folder is removed only
after its install succeeds and is verified.

The app checks whether a package is already installed before attempting an update. Signing-key
backups are integrity-checked, restores are activated atomically, and an existing identity is kept
in a recovery folder when it is replaced. The optional backup reminder appears only after a signed
build uses an identity that has not yet been backed up.

The optional older-firmware compatibility setting has the same narrow behavior as the released
app: when the source contains `lib/arm64-v8a/libovrplatformloader.so`, that existing ARM64 file is
replaced with the loader from Event Horizon, then the APK is rebuilt and signed normally. The
asset is pinned to one upstream revision and its SHA-256 is verified both before and after the
copy. The app never inserts the loader into an APK that did not already contain it.

The Bulk page accepts several APKs or folders, can scan direct children of a parent folder, and
previews one suffix across every package ID. Builds and installs run sequentially, one failure
does not stop later games, cancellation occurs at safe boundaries, and the final overview keeps
per-game success and failure details.

The dashboard accepts either a game folder or one exact `.apk` dropped onto it. Quick ID presets
include `.mr`, `.dev`, `.test`, and `.qa`; `.mr` inserts a mixed-reality tag after the first package
segment (for example, `com.studio.game` becomes `com.mr.studio.game`).

Device discovery handles connected, disconnected, unauthorized, offline, multiple-device,
missing-ADB, and Linux USB-permission states without blocking the interface.

Every Browse action uses one shared cross-platform picker chain: the operating system's native
dialog first, Qt's self-rendered dialog when desktop integration is broken, then the released
app's desktop-helper/Tk approach as a last resort. Cancelling a working dialog does not open the
next fallback.

Update checks run outside the UI thread and are optional. Manual checks are available in Settings,
new releases use a compact dismissible banner, and network failures never block APK work. The
updater follows the repository's normal `v…` GitHub release tags and preserves the published
ordering of the project's older out-of-sequence 1.8 and 1.9 tags.

Settings shows the exact pinned Apktool and APK-signer versions and verifies their SHA-256 hashes.
Missing or damaged JARs can be repaired automatically. Downloads run outside the UI thread, can be
cancelled safely, and are verified before an atomic replacement; repaired tools become available
immediately without restarting. The same verified component repair installs the pinned Event
Horizon compatibility loader when it is missing. Java and ADB continue to use packaged copies
first and compatible system installations as a fallback.

The separate Logs window follows the released app's developer-oriented model. A persistent 5 MB
rotating session log records UTC timestamps, operation stages, exact shell-free tool commands,
and complete Apktool, signer, and ADB output. Passwords and other supplied secret values are
redacted. The current log can be opened directly or exported as an exact copy; review local file
paths before sharing it. The window shows the current session without the noise from repeated app
launches, while the saved rotating log retains every session. **Copy support info** collects the app,
OS, Python/PySide, device and pinned-tool state plus the last 80 log lines into one readable block.
The text build report is intended for people, while the JSON report keeps the detailed structured
evidence needed by tools and issue reports. Failed operations offer the logs—and the relevant
build report when one exists—directly beside the failure.

Build recovery also survives an app crash or forced close. Before work begins, the engine records
the exact app-created sibling staging folder. On the next launch the app offers to open it, keep it,
or remove it; it never treats an arbitrary folder as recoverable output. Successful builds and
empty cancelled builds clear the record automatically.

Settings can also remove an old finished output. This is intentionally conservative: the folder
must contain a valid app-created JSON report naming an APK that is still present, the exact target
is shown for confirmation, and removal means moving it to the operating system Trash rather than
permanently deleting it.

The dedicated APK Inspector performs an opt-in full decode without changing the source. It shows
resolved app/version/SDK metadata, CPU architectures, locales, components, hashes, signature
schemes and certificates, known-signer identity, permissions/features, and an exact rename-impact
preview. Technical package references are separated from compiled/native or other preserved data,
embedded `Previously signed by …` lineage is shown explicitly, and the complete analysis can be
exported atomically as JSON. Inspection is cancellable and stays
separate from the faster automatic Dashboard analysis.

The interface supports keyboard navigation and visible focus states. `Ctrl+1` through `Ctrl+4`
switch pages, `Ctrl+O` opens the game picker, and `Ctrl+L` opens the standalone log window.
Destructive confirmations focus the safe choice by default, progress remains visible with both a
percentage and current stage, and the restrained transitions avoid delaying work.

The signer-lineage behavior, expanded seed registry, `.mr` preset, and single-APK drop on-ramp were
adapted from [PR #12](https://github.com/RockoTheeHut/Quest-APK-Renamer/pull/12) by
DeliciousMeatPop.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
quest-renamer
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

Run the real QML shell without leaving a window open (used by packaging CI):

```bash
quest-renamer --smoke-test
```

## Architecture

```text
src/quest_renamer/
├── domain/          Pure models, validation, and workflow rules
├── services/        Interfaces for build, install, device, and platform behavior
├── infrastructure/  Filesystem and operating-system implementations
├── presentation/    QML-facing controllers and view state
├── qml/             The complete Qt Quick interface
└── assets/          Application-owned visual assets
```

The domain and service layers must never import Qt. The presentation layer may translate domain
objects into properties and signals, but it does not perform APK or ADB work itself.

## Verify

```bash
pytest -q
ruff check src tests
mypy src
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for dependency and threading rules.
See [docs/PACKAGING.md](docs/PACKAGING.md) for portable builds, installers, macOS signing, and the
multi-platform release workflow.
