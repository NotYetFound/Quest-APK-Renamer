#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/../.." && pwd)"
runtime_dir="$script_dir/runtime"
python_bin="${PYTHON_BIN:-python3}"
force=0

if [[ "${1:-}" == "--force" ]]; then
    force=1
elif [[ -n "${1:-}" ]]; then
    echo "Usage: $0 [--force]" >&2
    exit 2
fi
if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    echo "This runtime bootstrap supports Linux x86_64." >&2
    exit 1
fi

temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/qar-linux.XXXXXX")"
trap 'rm -rf -- "$temp_dir"' EXIT
mkdir -p "$runtime_dir"
PYTHONPATH="$project_dir/src" "$python_bin" \
    "$project_dir/scripts/fetch_pinned_tools.py" "$runtime_dir" --project "$project_dir"

java_dir="$runtime_dir/java"
if [[ "$force" -eq 1 || ! -x "$java_dir/bin/java" || ! -x "$java_dir/bin/keytool" ]]; then
    archive="$temp_dir/temurin.tar.gz"
    extracted="$temp_dir/temurin"
    linked="$temp_dir/java"
    url="https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse"
    mkdir -p "$extracted"
    curl --fail --location --retry 3 "$url" --output "$archive"
    tar -xzf "$archive" -C "$extracted"
    jlink="$(find "$extracted" -type f -path '*/bin/jlink' -print -quit)"
    [[ -n "$jlink" ]] || { echo "Temurin did not contain jlink." >&2; exit 1; }
    "$jlink" --add-modules java.base,java.desktop,java.logging --strip-debug \
        --no-header-files --no-man-pages --compress=2 --output "$linked"
    rm -rf -- "$java_dir"
    mv "$linked" "$java_dir"
    printf 'Temurin archive SHA256: %s\nTemurin source: %s\n' \
        "$(sha256sum "$archive" | awk '{print $1}')" "$url" > "$runtime_dir/DEPENDENCY-HASHES.txt"
fi

platform_dir="$runtime_dir/platform-tools"
if [[ "$force" -eq 1 || ! -x "$platform_dir/adb" ]]; then
    archive="$temp_dir/platform-tools.zip"
    extracted="$temp_dir/android"
    url="https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    curl --fail --location --retry 3 "$url" --output "$archive"
    unzip -q "$archive" -d "$extracted"
    [[ -x "$extracted/platform-tools/adb" ]] || { echo "ADB was not found." >&2; exit 1; }
    rm -rf -- "$platform_dir"
    mv "$extracted/platform-tools" "$platform_dir"
    printf 'Platform-Tools archive SHA256: %s\nPlatform-Tools source: %s\n' \
        "$(sha256sum "$archive" | awk '{print $1}')" "$url" >> "$runtime_dir/DEPENDENCY-HASHES.txt"
fi

"$java_dir/bin/java" -jar "$runtime_dir/tools/apktool.jar" --version
"$java_dir/bin/java" -jar "$runtime_dir/tools/uber-apk-signer.jar" --help >/dev/null
"$java_dir/bin/keytool" -help >/dev/null 2>&1
"$platform_dir/adb" version
