# Windows build

The Windows port uses the same Python application and tests as Linux. The
packaged build includes:

- a windowed `Quest APK Renamer.exe` with no console;
- a trimmed Java 21 runtime created from Eclipse Temurin;
- Android SDK Platform-Tools (`adb.exe` and required DLLs);
- Apktool and Uber APK Signer; and
- TkinterDnD2 native drag-and-drop support.

## Build on Windows

Open PowerShell in the project directory and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

The portable application is created under:

```text
dist\Quest APK Renamer\
```

To also create `Quest-APK-Renamer-1.3.2-Setup.exe`, install Inno Setup 6 and
run:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1 -BuildInstaller
```

Tagged GitHub builds also create a portable ZIP. See
[`docs/RELEASING.md`](../docs/RELEASING.md) for the release checklist.

Runtime downloads come from the Eclipse Adoptium API and Google's official
Platform-Tools URL. The build uses `jlink` to keep only the Java modules the
two APK tools need. `windows\runtime\DEPENDENCY-HASHES.txt` records the
downloaded archive hashes, module list, and resolved versions for each build.

The installer is per-user and does not require administrator privileges.
These development builds are not code-signed, so Windows SmartScreen may show
an "Unknown publisher" warning until a trusted code-signing certificate is
added to the release process.
Uninstalling the program deliberately preserves the signing identity in:

```text
%LOCALAPPDATA%\Quest APK Renamer\
```

This prevents accidental loss of the key required for future renamed-app
updates.
