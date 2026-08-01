# Packaging Quest APK Renamer

Version 1.4 keeps the released application's **Quest APK Renamer** name, application-data paths,
Linux launcher path, Windows installer ID, and macOS bundle ID
`io.github.questapkrenamer.app`. Installing it upgrades the legacy application while preserving
settings and signing material.

## What every release contains

- The PySide6/QML application and only the Qt module families it imports.
- A trimmed Temurin 21 runtime containing Java, keytool, and their required modules.
- Android SDK Platform-Tools for ADB installation and device status.
- Checksum-pinned Apktool, Uber APK Signer, and Event Horizon compatibility loader files.
- MIT and third-party notices.
- A SHA-256 sidecar for every downloadable archive or installer.

Linux produces both a conventional portable tarball with launcher install helpers and a single-file
AppImage. The AppImage contains the same frozen application and verified Android toolchain; it does
not use or modify the tarball installation.

The Android components are verified against `src/quest_renamer/resources/toolchain.json` before
packaging. Java and ADB archives are downloaded from their official current-release endpoints and
their resolved hashes are written into the package's `DEPENDENCY-HASHES.txt`.

Release builds pin PySide6, PyInstaller, its hook collection, and pytest in
`packaging/requirements-build.txt`. The Linux release job builds on Ubuntu 22.04 rather than the
maintainer's desktop, giving the binary a stable glibc baseline for current x86_64 distributions.

## Local builds

Build on the target operating system and architecture. Cross-compiling Qt/PyInstaller desktop
bundles is intentionally unsupported.

```bash
# Linux x86_64
chmod +x packaging/linux/*.sh
packaging/linux/build.sh
```

This creates `Quest-APK-Renamer-<version>-Linux-x86_64.tar.gz` and
`Quest-APK-Renamer-<version>-x86_64.AppImage`, each with a `.sha256` sidecar. AppImage creation
uses checksum-pinned appimagetool 1.9.1 and type-2 runtime build 20251108. It launches the finished
image in extraction mode as its packaging smoke test, so CI does not require FUSE.

```powershell
# Windows x86_64; omit -BuildInstaller for portable-only output
packaging\windows\build.ps1 -BuildInstaller
```

```bash
# macOS arm64 or x86_64, using a native Python of the same architecture
chmod +x packaging/macos/*.sh
packaging/macos/build.sh
```

Pass `--skip-bootstrap` on Linux/macOS or `-SkipBootstrap` on Windows only when that platform's
`packaging/<platform>/runtime` directory is already complete. Build scripts run the test suite and
launch the packaged application in smoke-test mode before producing release archives.

## GitHub Actions releases

`.github/workflows/package.yml` builds Linux x86_64, Windows x86_64, macOS arm64, and macOS
x86_64. A tag matching `v<app version>` publishes the resulting files in one GitHub release;
a suffix such as `v1.4.0-beta.1` creates a prerelease.

macOS artifacts are ad-hoc signed when no credentials are configured. To produce a normal
Gatekeeper-friendly release, configure these repository secrets:

- `APPLE_CERTIFICATE_P12`
- `APPLE_CERTIFICATE_PASSWORD`
- `MACOS_CODESIGN_IDENTITY`
- `APPLE_ID`
- `APPLE_APP_PASSWORD`
- `APPLE_TEAM_ID`

The workflow then imports the Developer ID certificate into a temporary keychain, signs the app,
notarizes the DMG, staples the ticket, regenerates its checksum, and deletes the keychain.
