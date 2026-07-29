#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime_dir="$script_dir/runtime"
java_dir="$runtime_dir/java"
platform_tools_dir="$runtime_dir/platform-tools"
force=0

if [[ "${1:-}" == "--force" ]]; then
    force=1
elif [[ -n "${1:-}" ]]; then
    echo "Usage: $0 [--force]" >&2
    exit 2
fi

machine_arch="$(uname -m)"
if [[ "$machine_arch" != "x86_64" ]]; then
    echo "The bundled Linux release currently supports x86_64 only." >&2
    exit 1
fi

temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/quest-apk-renamer-linux.XXXXXX")"
cleanup() {
    rm -rf "$temp_dir"
}
trap cleanup EXIT

mkdir -p "$runtime_dir"
hash_file="$runtime_dir/DEPENDENCY-HASHES.txt"
: > "$hash_file"

if [[ "$force" -eq 1 || ! -x "$java_dir/bin/java" || ! -x "$java_dir/bin/keytool" ]]; then
    java_archive="$temp_dir/temurin-jre.tar.gz"
    java_extract="$temp_dir/temurin"
    java_url="https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jre/hotspot/normal/eclipse"
    mkdir -p "$java_extract"
    echo "Downloading Eclipse Temurin JRE 21..."
    curl --fail --location --retry 3 "$java_url" --output "$java_archive"
    tar -xzf "$java_archive" -C "$java_extract"
    extracted_java="$(find "$java_extract" -type f -path '*/bin/java' -print -quit)"
    if [[ -z "$extracted_java" ]]; then
        echo "The Temurin archive did not contain bin/java." >&2
        exit 1
    fi
    extracted_java="$(dirname "$(dirname "$extracted_java")")"
    if [[ ! -x "$extracted_java/bin/keytool" ]]; then
        echo "The Temurin runtime does not include keytool." >&2
        exit 1
    fi
    rm -rf "$java_dir"
    cp -a "$extracted_java" "$java_dir"
    {
        echo "Temurin JRE archive SHA256: $(sha256sum "$java_archive" | awk '{print $1}')"
        echo "Temurin source: $java_url"
    } >> "$hash_file"
else
    echo "Using existing bundled Java runtime."
fi

if [[ "$force" -eq 1 || ! -x "$platform_tools_dir/adb" ]]; then
    platform_archive="$temp_dir/platform-tools.zip"
    platform_extract="$temp_dir/android"
    platform_url="https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    mkdir -p "$platform_extract"
    echo "Downloading Android SDK Platform-Tools..."
    curl --fail --location --retry 3 "$platform_url" --output "$platform_archive"
    unzip -q "$platform_archive" -d "$platform_extract"
    extracted_tools="$platform_extract/platform-tools"
    if [[ ! -x "$extracted_tools/adb" ]]; then
        echo "The Platform-Tools archive did not contain adb." >&2
        exit 1
    fi
    rm -rf "$platform_tools_dir"
    cp -a "$extracted_tools" "$platform_tools_dir"
    {
        echo "Android Platform-Tools archive SHA256: $(sha256sum "$platform_archive" | awk '{print $1}')"
        echo "Platform-Tools source: $platform_url"
    } >> "$hash_file"
else
    echo "Using existing bundled Android Platform-Tools."
fi

{
    echo
    echo "Resolved Java:"
    "$java_dir/bin/java" -version 2>&1
    echo
    echo "Resolved ADB:"
    "$platform_tools_dir/adb" version 2>&1
} >> "$hash_file"

echo "Linux runtime dependencies are ready in $runtime_dir"
