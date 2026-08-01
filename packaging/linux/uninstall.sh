#!/usr/bin/env bash
set -euo pipefail

install_dir="${QAR_INSTALL_HOME:-$HOME/.local/opt}/quest-apk-renamer"
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
rm -f -- "$applications_dir/quest-apk-renamer.desktop"
[[ ! -d "$install_dir" ]] || rm -rf -- "$install_dir"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
echo "Application removed. Settings and signing keys were preserved."
