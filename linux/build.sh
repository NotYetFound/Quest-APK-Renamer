#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
runtime_dir="$script_dir/runtime"
venv_dir="$script_dir/.venv"
python_bin="$venv_dir/bin/python"
app_version="1.3.0"
package_name="Quest-APK-Renamer-${app_version}-Linux-x86_64"
package_dir="$project_dir/dist/$package_name"
archive_path="$project_dir/dist/$package_name.tar.gz"
skip_bootstrap=0

if [[ "${1:-}" == "--skip-bootstrap" ]]; then
    skip_bootstrap=1
elif [[ -n "${1:-}" ]]; then
    echo "Usage: $0 [--skip-bootstrap]" >&2
    exit 2
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    echo "The portable Linux bundle must be built on Linux x86_64." >&2
    exit 1
fi

if [[ ! -x "$python_bin" ]]; then
    python3 -m venv "$venv_dir"
fi
"$python_bin" -m pip install --upgrade pip
"$python_bin" -m pip install -r "$script_dir/requirements-build.txt"

if [[ "$skip_bootstrap" -eq 0 ]]; then
    "$script_dir/bootstrap-dependencies.sh"
fi
if [[ ! -x "$runtime_dir/java/bin/java" || ! -x "$runtime_dir/java/bin/keytool" ]]; then
    echo "Bundled Java and keytool are missing." >&2
    exit 1
fi
if [[ ! -x "$runtime_dir/platform-tools/adb" ]]; then
    echo "Bundled ADB is missing." >&2
    exit 1
fi

cd "$project_dir"
"$python_bin" -W error::ResourceWarning -m unittest discover -s tests -v
"$python_bin" -m PyInstaller \
    --noconfirm \
    --clean \
    "$script_dir/quest-apk-renamer.spec"

pyinstaller_dir="$project_dir/dist/Quest APK Renamer"
if [[ ! -x "$pyinstaller_dir/Quest APK Renamer" ]]; then
    echo "PyInstaller did not create the Linux executable." >&2
    exit 1
fi

rm -rf "$package_dir"
mkdir -p "$package_dir"
cp -a "$pyinstaller_dir"/. "$package_dir"/
cp "$script_dir/install.sh" "$package_dir/install.sh"
cp "$script_dir/uninstall.sh" "$package_dir/uninstall.sh"
cp "$script_dir/README.txt" "$package_dir/README.txt"
chmod +x "$package_dir/Quest APK Renamer" \
    "$package_dir/install.sh" \
    "$package_dir/uninstall.sh"

rm -f "$archive_path"
tar -czf "$archive_path" -C "$project_dir/dist" "$package_name"
(
    cd "$project_dir/dist"
    sha256sum "$(basename "$archive_path")" > SHA256SUMS-Linux-x86_64.txt
)

echo "Linux package created: $archive_path"
