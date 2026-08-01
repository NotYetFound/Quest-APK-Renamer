#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/../.." && pwd)"
venv_dir="$script_dir/.venv"
python_bin="$venv_dir/bin/python"
skip_bootstrap=0
build_dmg=1
for argument in "$@"; do
    case "$argument" in
        --skip-bootstrap) skip_bootstrap=1 ;;
        --no-dmg) build_dmg=0 ;;
        *) echo "Usage: $0 [--skip-bootstrap] [--no-dmg]" >&2; exit 2 ;;
    esac
done
[[ "$(uname -s)" == "Darwin" ]] || { echo "Build on macOS." >&2; exit 1; }
target_arch="${MACOS_TARGET_ARCH:-$(uname -m)}"
[[ "$target_arch" == "$(uname -m)" ]] || { echo "Use a native $target_arch Python runner." >&2; exit 1; }

[[ -x "$python_bin" ]] || python3 -m venv "$venv_dir"
"$python_bin" -m pip install --upgrade pip
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
generated="$script_dir/generated"
QT_QPA_PLATFORM=offscreen "$python_bin" "$project_dir/scripts/render_release_icons.py" "$generated" --project "$project_dir"
iconset="$generated/app-icon.iconset"
rm -rf -- "$iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    /usr/bin/sips -z "$size" "$size" "$generated/app-icon-1024.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double_size=$((size * 2))
    /usr/bin/sips -z "$double_size" "$double_size" "$generated/app-icon-1024.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$iconset" -o "$generated/app-icon.icns"

cd "$project_dir"
"$python_bin" -m pytest -q
QAR_PACKAGE_RUNTIME="$runtime_dir" QAR_PACKAGE_ICON="$generated/app-icon.icns" \
    APP_VERSION="$app_version" MACOS_TARGET_ARCH="$target_arch" \
    "$python_bin" -m PyInstaller --noconfirm --clean packaging/quest-apk-renamer.spec
app_path="$project_dir/dist/Quest APK Renamer.app"
"$app_path/Contents/MacOS/Quest APK Renamer" --smoke-test

identity="${MACOS_CODESIGN_IDENTITY:--}"
args=(--force --deep --sign "$identity")
if [[ "$identity" != "-" ]]; then
    args+=(--options runtime --timestamp --entitlements "$script_dir/entitlements.plist")
fi
/usr/bin/codesign "${args[@]}" "$app_path"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$app_path"
if [[ "$build_dmg" -eq 1 ]]; then
    stage="$(mktemp -d "${TMPDIR:-/tmp}/qar-dmg.XXXXXX")"
    trap 'rm -rf -- "$stage"' EXIT
    /usr/bin/ditto "$app_path" "$stage/Quest APK Renamer.app"
    ln -s /Applications "$stage/Applications"
    dmg="$project_dir/dist/Quest-APK-Renamer-${app_version}-macOS-${target_arch}.dmg"
    rm -f -- "$dmg"
    /usr/bin/hdiutil create -volname "Quest APK Renamer" -srcfolder "$stage" -ov -format UDZO "$dmg"
    (cd "$project_dir/dist" && shasum -a 256 "$(basename "$dmg")") > "$dmg.sha256"
fi
