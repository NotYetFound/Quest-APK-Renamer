# Third-party notices

Quest APK Renamer includes or downloads the components below. Each remains under its own
license and terms.

| Component | Version/build | License | Source |
| --- | --- | --- | --- |
| Qt / PySide6 | 6.x | LGPLv3/GPLv3 or commercial | [Qt for Python](https://doc.qt.io/qtforpython-6/) |
| PyInstaller | Build-time | GPLv2 with bootloader exception | [pyinstaller.org](https://pyinstaller.org/) |
| appimagetool | 1.9.1, build-time | MIT | [AppImage/appimagetool](https://github.com/AppImage/appimagetool) |
| AppImage type-2 runtime | 20251108 | MIT; embedded libraries retain their licenses | [AppImage/type2-runtime](https://github.com/AppImage/type2-runtime) |
| Apktool | 3.0.3 | Apache-2.0 | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) |
| Uber APK Signer | 1.3.0 | Apache-2.0 | [patrickfav/uber-apk-signer](https://github.com/patrickfav/uber-apk-signer) |
| Event Horizon loader | `9ffe7009` | MIT | [veygax/eventhorizon](https://github.com/veygax/eventhorizon) |
| Android SDK Platform-Tools | Resolved at build time | Android SDK terms | [Android developer tools](https://developer.android.com/tools/releases/platform-tools) |
| Eclipse Temurin | JDK 21 trimmed with `jlink` | GPLv2 with Classpath Exception | [Eclipse Adoptium](https://adoptium.net/) |

The three Android build/patch components are pinned in
`src/quest_renamer/resources/toolchain.json` and verified before packaging. Platform builds write
the resolved Java and ADB archive hashes to `runtime/DEPENDENCY-HASHES.txt`.
