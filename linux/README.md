# Linux build

The release build is a self-contained x86_64 folder packaged as a `.tar.gz`.
It includes Python/Tk, a trimmed Java runtime with `keytool`, Android
Platform-Tools, Apktool, the APK signer, and drag-and-drop support.

## Build

Install Python 3.10 or newer with Tk, `venv`, `curl`, `unzip`, and `tar`, then:

```bash
chmod +x linux/build.sh linux/bootstrap-dependencies.sh
./linux/build.sh
```

Artifacts are written to `dist/`:

- `Quest-APK-Renamer-1.3.2-Linux-x86_64.tar.gz`

The extracted bundle includes `install.sh` for a per-user installation under
`~/.local/opt/quest-apk-renamer` and an app-launcher entry. No administrator
access is required. `uninstall.sh` removes the app while intentionally
preserving signing keys and settings.

## Runtime compatibility

- CPU: x86_64
- libc: glibc 2.35 or newer
- sessions: Wayland or X11
- desktops: GNOME, KDE Plasma, Xfce, Cinnamon, MATE, LXQt, COSMIC, and other
  freedesktop-compatible environments

The app chooses `zenity`, `kdialog`, or `yad` based on the active desktop and
falls back to bundled Tk when the preferred helper is missing or broken.
External dialog helpers are optional. Opening files uses `xdg-open` or `gio`,
while safe Trash support uses `gio trash` or `trash-put` when available.

ADB may require distro-provided Android udev rules before a normal user can
access a USB-connected Quest. The device card identifies that condition
separately from an unapproved USB-debugging prompt.

The bootstrap downloads Eclipse Temurin JDK 21 and uses `jlink` to keep only
the Java modules required by Apktool, the signer, and `keytool`.
