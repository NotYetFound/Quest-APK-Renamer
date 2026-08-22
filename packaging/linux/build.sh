#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/../.." && pwd)"
venv_dir="$script_dir/.venv"
python_bin="$venv_dir/bin/python"
skip_bootstrap=0
[[ "${1:-}" == "--skip-bootstrap" ]] && skip_bootstrap=1
[[ -z "${1:-}" || "${1:-}" == "--skip-bootstrap" ]] || { echo "Usage: $0 [--skip-bootstrap]" >&2; exit 2; }
[[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || { echo "Build on Linux x86_64." >&2; exit 1; }

[[ -x "$python_bin" ]] || python3 -m venv "$venv_dir"
"$python_bin" -m pip install "pip==26.2.1"
"$python_bin" -m pip install -r "$project_dir/packaging/requirements-build.txt" -e "$project_dir"
if [[ "$skip_bootstrap" -eq 0 ]]; then
    PYTHON_BIN="$python_bin" "$script_dir/bootstrap-dependencies.sh"
fi
runtime_dir="$script_dir/runtime"
required_runtime_files=(
    "$runtime_dir/java/bin/java"
    "$runtime_dir/java/bin/keytool"
    "$runtime_dir/platform-tools/adb"
    "$runtime_dir/tools/apktool.jar"
    "$runtime_dir/tools/uber-apk-signer.jar"
    "$runtime_dir/tools/libovrplatformloader.so"
)
for required_file in "${required_runtime_files[@]}"; do
    [[ -e "$required_file" ]] || { echo "Bundled runtime is incomplete: missing $required_file" >&2; exit 1; }
done

app_version="$(PYTHONPATH="$project_dir/src" "$python_bin" -c 'from quest_renamer import __version__; print(__version__)')"
icon_dir="$script_dir/generated"
QT_QPA_PLATFORM=offscreen "$python_bin" "$project_dir/scripts/render_release_icons.py" "$icon_dir" --project "$project_dir"
cd "$project_dir"
"$python_bin" -m pytest -q
QAR_PACKAGE_RUNTIME="$runtime_dir" QAR_PACKAGE_ICON="$icon_dir/app-icon-1024.png" APP_VERSION="$app_version" \
    "$python_bin" -m PyInstaller --noconfirm --clean packaging/quest-apk-renamer.spec
app_dir="$project_dir/dist/Quest APK Renamer"
bundled_ca="$app_dir/_internal/certifi/cacert.pem"
[[ -f "$bundled_ca" ]] || {
    echo "Frozen app is missing the CA certificate bundle required for update checks." >&2
    exit 1
}
QT_QPA_PLATFORM=offscreen "$app_dir/Quest APK Renamer" --smoke-test

package_name="Quest-APK-Renamer-${app_version}-Linux-x86_64"
package_dir="$project_dir/dist/$package_name"
archive="$project_dir/dist/$package_name.tar.gz"
rm -rf -- "$package_dir"
mkdir -p "$package_dir"
cp -a "$app_dir"/. "$package_dir"/
cp "$script_dir/install.sh" "$script_dir/uninstall.sh" "$script_dir/README.txt" "$package_dir"/
chmod +x "$package_dir/Quest APK Renamer" "$package_dir/install.sh" "$package_dir/uninstall.sh"
tar -czf "$archive" -C "$project_dir/dist" "$package_name"
(cd "$project_dir/dist" && sha256sum "$(basename "$archive")") > "$archive.sha256"
echo "Created $archive"

appimage_tool="$icon_dir/appimagetool-x86_64.AppImage"
appimage_tool_url="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
appimage_tool_sha256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
if [[ ! -f "$appimage_tool" ]] || ! printf '%s  %s\n' "$appimage_tool_sha256" "$appimage_tool" | sha256sum --check --status; then
    download="$icon_dir/appimagetool-x86_64.AppImage.download"
    curl --fail --location --retry 3 "$appimage_tool_url" --output "$download"
    printf '%s  %s\n' "$appimage_tool_sha256" "$download" | sha256sum --check --status || {
        echo "Downloaded appimagetool did not match its pinned SHA-256." >&2
        exit 1
    }
    mv "$download" "$appimage_tool"
fi
chmod +x "$appimage_tool"

appimage_runtime="$icon_dir/runtime-x86_64"
appimage_runtime_url="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
appimage_runtime_sha256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
if [[ ! -f "$appimage_runtime" ]] || ! printf '%s  %s\n' "$appimage_runtime_sha256" "$appimage_runtime" | sha256sum --check --status; then
    download="$icon_dir/runtime-x86_64.download"
    curl --fail --location --retry 3 "$appimage_runtime_url" --output "$download"
    printf '%s  %s\n' "$appimage_runtime_sha256" "$download" | sha256sum --check --status || {
        echo "Downloaded AppImage runtime did not match its pinned SHA-256." >&2
        exit 1
    }
    mv "$download" "$appimage_runtime"
fi

appimage_root="$project_dir/dist/AppDir"
appimage="$project_dir/dist/Quest-APK-Renamer-${app_version}-x86_64.AppImage"
rm -rf -- "$appimage_root"
mkdir -p \
    "$appimage_root/usr/bin" \
    "$appimage_root/usr/lib/quest-apk-renamer" \
    "$appimage_root/usr/share/applications" \
    "$appimage_root/usr/share/icons/hicolor/scalable/apps" \
    "$appimage_root/usr/share/metainfo"
cp -a "$app_dir"/. "$appimage_root/usr/lib/quest-apk-renamer"/
cp "$script_dir/AppRun" "$appimage_root/AppRun"
cp "$script_dir/io.github.questapkrenamer.app.desktop" \
    "$appimage_root/io.github.questapkrenamer.app.desktop"
cp "$script_dir/io.github.questapkrenamer.app.desktop" "$appimage_root/usr/share/applications/"
cp "$project_dir/src/quest_renamer/assets/app-icon.svg" "$appimage_root/quest-apk-renamer.svg"
cp "$project_dir/src/quest_renamer/assets/app-icon.svg" \
    "$appimage_root/usr/share/icons/hicolor/scalable/apps/quest-apk-renamer.svg"
cp "$script_dir/io.github.questapkrenamer.app.appdata.xml" "$appimage_root/usr/share/metainfo/"
ln -s "../lib/quest-apk-renamer/Quest APK Renamer" \
    "$appimage_root/usr/bin/quest-apk-renamer"
chmod +x "$appimage_root/AppRun" \
    "$appimage_root/usr/lib/quest-apk-renamer/Quest APK Renamer"
command -v desktop-file-validate >/dev/null 2>&1 && \
    desktop-file-validate "$appimage_root/io.github.questapkrenamer.app.desktop"
ARCH=x86_64 VERSION="$app_version" "$appimage_tool" --appimage-extract-and-run \
    --no-appstream --runtime-file "$appimage_runtime" "$appimage_root" "$appimage"
chmod +x "$appimage"
QT_QPA_PLATFORM=offscreen "$appimage" --appimage-extract-and-run --smoke-test
(cd "$project_dir/dist" && sha256sum "$(basename "$appimage")") > "$appimage.sha256"
echo "Created $appimage"
