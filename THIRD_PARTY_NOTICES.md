# Third-party notices

Quest APK Renamer includes or downloads the following third-party components.
Each component remains under its own license.

| Component | Version/build | License | Source |
| --- | --- | --- | --- |
| Apktool | 3.0.3 | Apache License 2.0 | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) |
| Uber APK Signer | 1.3.0 | Apache License 2.0 | [patrickfav/uber-apk-signer](https://github.com/patrickfav/uber-apk-signer) |
| TkinterDnD2 / tkdnd | 0.6.2 | MIT-style licenses | [Eliav2/tkinterdnd2](https://github.com/Eliav2/tkinterdnd2) |
| Event Horizon compatibility loader | `9ffe700` | MIT | [veygax/eventhorizon](https://github.com/veygax/eventhorizon) |
| Android SDK Platform-Tools | Resolved at Windows/macOS/Linux build time | Android SDK terms | [Android developer tools](https://developer.android.com/tools/releases/platform-tools) |
| Eclipse Temurin | JDK 21 used at build time to create a trimmed Java runtime | GPLv2 with Classpath Exception and related notices | [Eclipse Adoptium](https://adoptium.net/) |

Exact hashes for the two repository-bundled JARs are recorded in
`tools/versions.json`. Windows, macOS, and Linux builds also generate a
platform-specific `runtime/DEPENDENCY-HASHES.txt` for the downloaded Java and
ADB archives. Release packages contain only the Java modules required by
Apktool, Uber APK Signer, and `keytool`.

The Event Horizon `libovrplatformloader.so` asset is pinned and verified using
the provenance and SHA-256 checksum recorded in
`assets/patches/ovrplatform/SOURCE.md`. It is only used when the optional older
firmware compatibility setting is enabled.

The component distributions may contain additional license and notice files.
Those files and upstream terms control if this summary differs from them.
