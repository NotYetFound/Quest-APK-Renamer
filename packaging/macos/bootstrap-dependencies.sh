#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/../.." && pwd)"
runtime_dir="$script_dir/runtime"
lock_file="$project_dir/packaging/runtime-lock.json"
python_bin="${PYTHON_BIN:-python3}"
force=0
[[ "${1:-}" == "--force" ]] && force=1
[[ -z "${1:-}" || "${1:-}" == "--force" ]] || { echo "Usage: $0 [--force]" >&2; exit 2; }
[[ "$(uname -s)" == "Darwin" ]] || { echo "Run this on macOS." >&2; exit 1; }
case "$(uname -m)" in
    arm64) runtime_platform="macos-arm64" ;;
    x86_64) runtime_platform="macos-x86_64" ;;
    *) echo "Unsupported macOS architecture." >&2; exit 1 ;;
esac

temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/qar-macos.XXXXXX")"
trap 'rm -rf -- "$temp_dir"' EXIT
mkdir -p "$runtime_dir"
PYTHONPATH="$project_dir/src" "$python_bin" \
    "$project_dir/scripts/fetch_pinned_tools.py" "$runtime_dir" --project "$project_dir"

java_dir="$runtime_dir/java"
IFS=$'\t' read -r java_url java_sha java_version < <(
    "$python_bin" "$project_dir/scripts/read_runtime_lock.py" \
        "$lock_file" temurin "$runtime_platform"
)
if [[ "$force" -eq 1 || ! -x "$java_dir/bin/java" || ! -x "$java_dir/bin/keytool" ]]; then
    archive="$temp_dir/temurin.tar.gz"
    extracted="$temp_dir/temurin"
    linked="$temp_dir/java"
    mkdir -p "$extracted"
    curl --fail --location --retry 3 "$java_url" --output "$archive"
    actual_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"
    [[ "$actual_sha" == "$java_sha" ]] || {
        echo "Temurin SHA-256 mismatch; refusing to use the download." >&2
        exit 1
    }
    tar -xzf "$archive" -C "$extracted"
    jlink="$(find "$extracted" -type f -path '*/Contents/Home/bin/jlink' -print -quit)"
    [[ -n "$jlink" ]] || { echo "Temurin did not contain jlink." >&2; exit 1; }
    "$jlink" --add-modules java.base,java.desktop,java.logging --strip-debug \
        --no-header-files --no-man-pages --compress=2 --output "$linked"
    rm -rf -- "$java_dir"
    /usr/bin/ditto "$linked" "$java_dir"
fi

platform_dir="$runtime_dir/platform-tools"
IFS=$'\t' read -r platform_url platform_sha platform_version < <(
    "$python_bin" "$project_dir/scripts/read_runtime_lock.py" \
        "$lock_file" platform_tools "$runtime_platform"
)
if [[ "$force" -eq 1 || ! -x "$platform_dir/adb" ]]; then
    archive="$temp_dir/platform-tools.zip"
    extracted="$temp_dir/android"
    curl --fail --location --retry 3 "$platform_url" --output "$archive"
    actual_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"
    [[ "$actual_sha" == "$platform_sha" ]] || {
        echo "Platform Tools SHA-256 mismatch; refusing to use the download." >&2
        exit 1
    }
    mkdir -p "$extracted"
    /usr/bin/ditto -x -k "$archive" "$extracted"
    [[ -x "$extracted/platform-tools/adb" ]] || { echo "ADB was not found." >&2; exit 1; }
    rm -rf -- "$platform_dir"
    /usr/bin/ditto "$extracted/platform-tools" "$platform_dir"
fi

printf 'Temurin version: %s\nTemurin archive SHA256: %s\nTemurin source: %s\nPlatform-Tools version: %s\nPlatform-Tools archive SHA256: %s\nPlatform-Tools source: %s\n' \
    "$java_version" "$java_sha" "$java_url" \
    "$platform_version" "$platform_sha" "$platform_url" \
    > "$runtime_dir/DEPENDENCY-HASHES.txt"

"$java_dir/bin/java" -jar "$runtime_dir/tools/apktool.jar" --version
"$java_dir/bin/java" -jar "$runtime_dir/tools/uber-apk-signer.jar" --help >/dev/null
"$java_dir/bin/keytool" -help >/dev/null 2>&1
"$platform_dir/adb" version
