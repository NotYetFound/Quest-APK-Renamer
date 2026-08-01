#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_parent="${QAR_INSTALL_HOME:-$HOME/.local/opt}"
install_dir="$install_parent/quest-apk-renamer"
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_file="$applications_dir/quest-apk-renamer.desktop"
[[ -x "$script_dir/Quest APK Renamer" ]] || { echo "Run this inside the extracted release folder." >&2; exit 1; }
mkdir -p "$install_parent" "$applications_dir"
backup_dir=""
if [[ -e "$install_dir" ]]; then
    backup_dir="$install_parent/quest-apk-renamer.previous.$(date +%Y%m%d%H%M%S)"
    mv "$install_dir" "$backup_dir"
fi
if ! cp -a "$script_dir" "$install_dir"; then
    [[ -z "$backup_dir" || ! -e "$backup_dir" ]] || mv "$backup_dir" "$install_dir"
    exit 1
fi
{
    echo '[Desktop Entry]'
    echo 'Type=Application'
    echo 'Name=Quest APK Renamer'
    echo 'Comment=Build and install separate authorized Quest test bundles'
    printf 'Exec="%s/Quest APK Renamer"\n' "$install_dir"
    printf 'Icon=%s/_internal/quest_renamer/assets/app-icon.svg\n' "$install_dir"
    echo 'Terminal=false'
    echo 'Categories=Development;'
    echo 'StartupNotify=true'
} > "$desktop_file"
chmod 644 "$desktop_file"
[[ -z "$backup_dir" || ! -e "$backup_dir" ]] || rm -rf -- "$backup_dir"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
echo "Installed Quest APK Renamer. App data and signing keys are kept separately."
