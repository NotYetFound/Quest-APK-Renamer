#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_parent="${XDG_INSTALL_HOME:-$HOME/.local/opt}"
install_dir="$install_parent/quest-apk-renamer"
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_file="$applications_dir/quest-apk-renamer.desktop"
app_data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/quest-apk-renamer"
backup_dir=""

if [[ ! -x "$script_dir/Quest APK Renamer" ]]; then
    echo "Run install.sh from inside the extracted Quest APK Renamer folder." >&2
    exit 1
fi

mkdir -p "$install_parent" "$applications_dir"
if [[ -e "$install_dir" ]]; then
    backup_dir="$install_parent/quest-apk-renamer.previous.$(date +%Y%m%d%H%M%S)"
    mv "$install_dir" "$backup_dir"
fi

if ! cp -a "$script_dir" "$install_dir"; then
    if [[ -n "$backup_dir" && -e "$backup_dir" ]]; then
        mv "$backup_dir" "$install_dir"
    fi
    echo "Installation failed; the previous version was restored." >&2
    exit 1
fi

cat > "$desktop_file" <<EOF
[Desktop Entry]
Type=Application
Name=Quest APK Renamer
Comment=Rename and install authorized Quest APK/OBB bundles
Exec="$install_dir/Quest APK Renamer"
Icon=$install_dir/_internal/assets/quest-apk-renamer.png
Terminal=false
Categories=Utility;Development;
StartupNotify=true
EOF
chmod 644 "$desktop_file"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
fi
if [[ -n "$backup_dir" && -e "$backup_dir" ]]; then
    rm -rf "$backup_dir"
fi

echo "Quest APK Renamer is installed."
echo "Open it from your app launcher or run:"
echo "  $install_dir/Quest APK Renamer"
echo "Signing keys and settings remain in $app_data_dir."
