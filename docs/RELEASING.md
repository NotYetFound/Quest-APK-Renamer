# Release checklist

This checklist is for maintainers preparing a tagged GitHub release.

## Repository setup

Suggested GitHub repository description:

> Rename, rebuild, sign, and install authorized Meta Quest APK/OBB bundles from
> a beginner-friendly desktop app.

Suggested topics:

```text
meta-quest android apk obb adb qt qml python desktop-app
```

Enable **Issues**, **Actions**, and **Private vulnerability reporting** in the
repository settings. The release workflow needs `contents: write` permission
for the repository-provided `GITHUB_TOKEN`.

## 1. Confirm the release

- Decide whether the build is alpha, beta, release candidate, or stable.
- Update `__version__` in `src/quest_renamer/__init__.py`.
- Confirm the common version is used by the PyInstaller spec and all three
  platform packaging scripts.
- Update the README release-candidate line.
- Add the dated entry to `CHANGELOG.md`.
- Confirm that the MIT copyright line still names the intended holder.

## 2. Test

Run:

```bash
python -m pip install -e '.[dev]'
ruff check src tests scripts
mypy src
pytest -q
QT_QPA_PLATFORM=offscreen quest-renamer --smoke-test
```

On a real Windows x64 computer:

- build the installer;
- launch the installed app from the Start Menu;
- confirm drag-and-drop and native folder selection;
- confirm Java, `keytool`, ADB, Apktool, and the signer are detected;
- connect an authorized Quest;
- build a test bundle you are permitted to modify;
- install its APK and OBB;
- verify cancellation and failed-OBB retry behavior; and
- uninstall the desktop app and confirm the signing-key folder is preserved.

On both an Apple Silicon Mac and an Intel Mac:

- build or download the matching DMG;
- drag the app into Applications and launch it;
- confirm Finder drag-and-drop and the native folder/multi-APK pickers;
- confirm Java, `keytool`, ADB, Apktool, and the signer are detected;
- confirm Finder Trash cleanup with a disposable app-created output;
- connect an authorized Quest and complete one build/install/verify cycle;
- confirm the signing key is stored under
  `~/Library/Application Support/Quest APK Renamer/`; and
- remove the app and confirm the signing-key directory is preserved.

On a Linux x86_64 computer:

- extract the release archive and run `./install.sh`;
- launch the app from the desktop app launcher;
- confirm the generated launcher targets the packaged executable;
- confirm Java, `keytool`, ADB, Apktool, and the signer are detected;
- confirm drag-and-drop and folder selection on both Wayland and X11;
- test picker preference/fallback on GNOME-family and KDE-family desktops;
- confirm a missing `~/Downloads` folder still opens a usable picker;
- confirm an ADB `no permissions` device shows the Linux udev guidance;
- connect an authorized Quest and complete one build/install/verify cycle;
- run `./uninstall.sh`; and
- confirm `~/.local/share/quest-apk-renamer/` and its signing key are preserved.

## 3. Review release materials

- Confirm all screenshots match the current UI.
- Confirm no screenshot or log contains private paths, serials, or game data.
- Check `THIRD_PARTY_NOTICES.md` against packaged dependency versions.
- Scan the repository for APK, OBB, keystore, and credential files.
- Confirm the Windows installer is expected to show **Unknown publisher** until
  a trusted code-signing certificate is configured.
- Confirm macOS Gatekeeper behavior matches the signing/notarization state.

### Optional Apple release signing

The macOS workflow uses ad-hoc signing when Apple credentials are absent. For
a normal Gatekeeper experience, configure these GitHub Actions secrets:

- `APPLE_CERTIFICATE_P12` — base64-encoded Developer ID Application `.p12`;
- `APPLE_CERTIFICATE_PASSWORD` — password for that `.p12`;
- `MACOS_CODESIGN_IDENTITY` — full Developer ID Application identity;
- `APPLE_ID` — Apple developer account email;
- `APPLE_APP_PASSWORD` — app-specific password; and
- `APPLE_TEAM_ID` — Apple Developer team identifier.

The first three enable Developer ID signing. All six enable notarization and
stapling. Never place these values in the repository or workflow files.

## 4. Tag and build

Start a manual package run from the candidate branch first. This produces all
four platform artifacts without publishing a release. After those exact files
pass the checks above, create the stable tag:

```bash
git tag -a v1.4.2 -m "Quest APK Renamer 1.4.2"
git push origin v1.4.2
```

The release workflows build:

- `Quest-APK-Renamer-1.4.2-Windows-portable.zip`;
- `Quest-APK-Renamer-1.4.2-Setup.exe`;
- `Quest-APK-Renamer-1.4.2-macOS-arm64.dmg`;
- `Quest-APK-Renamer-1.4.2-macOS-x86_64.dmg`;
- `Quest-APK-Renamer-1.4.2-Linux-x86_64.tar.gz`; and
- `Quest-APK-Renamer-1.4.2-x86_64.AppImage`.

GitHub displays a copyable SHA-256 digest beside every uploaded release asset.

A `v*` tag creates a GitHub release automatically. A tag may match the app
version exactly or add a prerelease suffix. For example, app version `1.4.2`
accepts `v1.4.2` or `v1.4.2-beta.1`. Tags containing a hyphen are marked as
prereleases. Create the stable `v1.4.2` tag only after the candidate Windows,
macOS, and Linux packages pass their complete desktop and Quest smoke tests.

## 5. Before publishing

- Download the workflow artifacts onto a separate Windows machine.
- Download each DMG onto a matching Apple Silicon or Intel Mac.
- Download the Linux archive onto a clean x86_64 Linux computer.
- Verify every package against its CI-generated SHA-256 sidecar. The sidecars
  remain workflow artifacts and are not uploaded as separate release downloads.
- Install and launch the exact uploaded installer.
- Install and launch both exact uploaded DMGs.
- Install and launch the exact uploaded Linux bundle.
- Review the generated GitHub release notes.
- Mark the release stable only after the Windows, macOS, Linux, and Quest
  smoke tests pass.
