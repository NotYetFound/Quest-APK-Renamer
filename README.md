# Quest APK Renamer
[![Latest release](https://img.shields.io/github/v/release/NotYetFound/Quest-APK-Renamer?display_name=tag&sort=semver)](https://github.com/NotYetFound/Quest-APK-Renamer/releases/latest)
[![Tests](https://github.com/NotYetFound/Quest-APK-Renamer/actions/workflows/test.yml/badge.svg)](https://github.com/NotYetFound/Quest-APK-Renamer/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Quest APK Renamer creates a second copy of a Meta Quest APK with a different Android package ID, allowing it to be installed beside the original game.
It can rename, rebuild, sign, verify, and install APKs and their OBB files directly to your Quest.

Available for Windows, Linux, and macOS. Release packages include the required Android tools, so no Android SDK setup is needed.
> This project was made with AI assistance. Expect bugs, keep backups, and use it carefully.
![Quest APK Renamer dashboard](docs/screenshots/dashboard.png)
## Download
Download the latest version from the [GitHub Releases page](https://github.com/NotYetFound/Quest-APK-Renamer/releases/latest).
| Platform | Download |
| --- | --- |
| Windows 10/11 x64 | Installer or portable ZIP |
| Linux x86_64 | AppImage or portable tarball |
| Apple Silicon macOS | ARM64 DMG |
| Intel macOS | x86_64 DMG |
Windows builds are currently unsigned and macOS builds are not notarized, so your operating system may show an unknown developer warning.
## Quick Start
1. Select an APK or a folder containing an APK and its OBB files.
2. Choose the new package ID. A safe suggestion is created automatically.
3. Click **Build renamed copy**.
4. Connect your Quest and approve USB debugging.
5. Click **Install built game**.
The renamed APK and OBB files are saved in a separate ` - Renamed` folder. Your original files are not modified unless **Replace source after build** is enabled.
## Main Features
- Rename Quest APK package IDs
- Install renamed copies beside the original game
- Automatic APK and OBB handling
- APK rebuilding, signing, and verification
- USB and wireless ADB support
- Automatic Quest detection
- APK Inspector
- Bulk APK rename/install queue
- Installed game Library
- Saved signing identities for future updates
- Signing identity backup and restore
- Automatic Android tool checks and repair
- Build and installation progress
- Detailed logs and support information
- And more...
## Wireless Quest Connection
You can connect using USB or wireless ADB.
Connect the Quest over USB first and use **Enable wireless ADB over USB** to switch it to Wi-Fi. Saved Quest addresses can then be reconnected from the app.
You can also manually add an `ip:port` address from the Quest's Wireless Debugging screen.
## Updating Renamed Games
The **Library** keeps track of renamed games and their signing identities.
When you select a newer version of the same game, Quest APK Renamer can rebuild it using the same package ID and signing key so it can update the renamed copy already installed on your headset.
Keep a backup of your signing identity. Losing the signing key means Android will not allow future builds to update the existing renamed installation.
## Platform Notes
### Windows
The installer adds Quest APK Renamer to the Start Menu. SmartScreen may warn about an unknown publisher because the application is not currently code-signed.
### macOS
The DMGs are not currently notarized. You may need to Control-click the app, choose **Open**, and confirm the warning on first launch.
### Linux
Use the AppImage or portable tarball. Some Linux distributions may require an Android udev rule before ADB can access the Quest.
Developer Mode and USB debugging must be enabled on the headset.
## Safety
Only use Quest APK Renamer with applications you own or have permission to modify.
Quest APK Renamer does not bypass:
- Meta entitlements
- Game accounts
- Licensing
- DRM
- Platform security
Renamed APKs are re-signed with a different certificate, so they are treated by Android as separate builds.
Keep backups of important APKs, OBB files, and your Quest APK Renamer signing identity.
## Problems or Bugs
If something goes wrong, use **Copy support info** from the Logs window and [open a GitHub issue](https://github.com/NotYetFound/Quest-APK-Renamer/issues/new/choose).
## Run From Source
Python 3.11 or newer is required.
~~~bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
quest-renamer
~~~
Run the project checks with:
~~~bash
ruff check src tests scripts
mypy src
pytest -q
QT_QPA_PLATFORM=offscreen quest-renamer --smoke-test
~~~
Release builds bundle the required Java, ADB, Apktool, and signing tools. Source checkouts require compatible tools to be available on the system.
## Documentation
- [Architecture](docs/ARCHITECTURE.md)
- [Packaging](docs/PACKAGING.md)
- [Release checklist](docs/RELEASING.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
Quest APK Renamer is released under the [MIT License](LICENSE).