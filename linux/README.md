# Linux build

The release build is a self-contained x86_64 folder packaged as a `.tar.gz`.
It includes Python/Tk, Java and `keytool`, Android Platform-Tools, Apktool, the
APK signer, and drag-and-drop support.

## Build

Install Python 3.10 or newer with Tk, `venv`, `curl`, `unzip`, and `tar`, then:

```bash
chmod +x linux/build.sh linux/bootstrap-dependencies.sh
./linux/build.sh
```

Artifacts are written to `dist/`:

- `Quest-APK-Renamer-1.8.0-Linux-x86_64.tar.gz`
- `SHA256SUMS-Linux-x86_64.txt`

The extracted bundle includes `install.sh` for a per-user installation under
`~/.local/opt/quest-apk-renamer` and an app-launcher entry. No administrator
access is required. `uninstall.sh` removes the app while intentionally
preserving signing keys and settings.
