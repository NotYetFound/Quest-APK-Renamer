#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
runtime_dir="$script_dir/runtime"
venv_dir="$script_dir/.venv"
python_bin="$venv_dir/bin/python"
app_version="1.3.0"
skip_bootstrap=0
build_dmg=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-bootstrap)
            skip_bootstrap=1
            ;;
        --no-dmg)
            build_dmg=0
            ;;
        *)
            echo "Usage: $0 [--skip-bootstrap] [--no-dmg]" >&2
            exit 2
            ;;
    esac
    shift
done

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "The macOS app must be built on macOS." >&2
    exit 1
fi

machine_arch="$(uname -m)"
target_arch="${MACOS_TARGET_ARCH:-$machine_arch}"
if [[ "$target_arch" != "$machine_arch" ]]; then
    echo "Target $target_arch requires a native $target_arch Python runner." >&2
    exit 1
fi
case "$target_arch" in
    arm64|x86_64)
        ;;
    *)
        echo "Unsupported macOS architecture: $target_arch" >&2
        exit 1
        ;;
esac

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

iconset="$runtime_dir/quest-apk-renamer.iconset"
icon_source="$project_dir/assets/quest-apk-renamer-1024.png"
icon_output="$runtime_dir/quest-apk-renamer.icns"
rm -rf "$iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    /usr/bin/sips -z "$size" "$size" "$icon_source" \
        --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double_size=$((size * 2))
    /usr/bin/sips -z "$double_size" "$double_size" "$icon_source" \
        --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$iconset" -o "$icon_output"
rm -rf "$iconset"

cd "$project_dir"
"$python_bin" -m unittest discover -s tests -v
MACOS_TARGET_ARCH="$target_arch" \
    "$python_bin" -m PyInstaller \
    --noconfirm \
    --clean \
    "$script_dir/quest-apk-renamer.spec"

app_path="$project_dir/dist/Quest APK Renamer.app"
if [[ ! -d "$app_path" ]]; then
    echo "PyInstaller did not create the app bundle." >&2
    exit 1
fi

codesign_identity="${MACOS_CODESIGN_IDENTITY:--}"
codesign_args=(
    --force
    --deep
    --sign "$codesign_identity"
)
if [[ "$codesign_identity" != "-" ]]; then
    codesign_args+=(
        --options runtime
        --timestamp
        --entitlements "$script_dir/entitlements.plist"
    )
fi
/usr/bin/codesign "${codesign_args[@]}" "$app_path"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$app_path"

if [[ "$build_dmg" -eq 1 ]]; then
    dmg_stage="$(mktemp -d "${TMPDIR:-/tmp}/quest-apk-renamer-dmg.XXXXXX")"
    cleanup_dmg_stage() {
        rm -rf "$dmg_stage"
    }
    trap cleanup_dmg_stage EXIT
    /usr/bin/ditto "$app_path" "$dmg_stage/Quest APK Renamer.app"
    ln -s /Applications "$dmg_stage/Applications"
    dmg_path="$project_dir/dist/Quest-APK-Renamer-${app_version}-macOS-${target_arch}.dmg"
    rm -f "$dmg_path"
    /usr/bin/hdiutil create \
        -volname "Quest APK Renamer" \
        -srcfolder "$dmg_stage" \
        -ov \
        -format UDZO \
        "$dmg_path"
    echo "macOS DMG created: $dmg_path"
fi

echo "macOS build complete: $project_dir/dist"
