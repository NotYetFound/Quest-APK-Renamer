#!/usr/bin/env bash
set -euo pipefail

install_parent="${XDG_INSTALL_HOME:-$HOME/.local/opt}"
install_dir="$install_parent/quest-apk-renamer"
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_file="$applications_dir/quest-apk-renamer.desktop"
app_data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/quest-apk-renamer"

rm -f "$desktop_file"
if [[ -d "$install_dir" ]]; then
    rm -rf "$install_dir"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
fi

echo "Quest APK Renamer was removed."
echo "Signing keys and settings were preserved in $app_data_dir."
