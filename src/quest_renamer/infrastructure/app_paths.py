"""Cross-platform locations with no dependency on a GUI toolkit."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    data: Path
    cache: Path

    @property
    def settings_file(self) -> Path:
        return self.data / "settings.json"

    @property
    def log_file(self) -> Path:
        return self.data / "logs" / "activity.log"

    @property
    def build_recovery_file(self) -> Path:
        return self.data / "build-recovery.json"

    @property
    def library_file(self) -> Path:
        return self.data / "library.json"


def platform_app_paths(
    *,
    system: str | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> AppPaths:
    system = system or sys.platform
    environment = environment if environment is not None else os.environ
    home = (home or Path.home()).expanduser()

    if system.startswith("win"):
        local = Path(environment.get("LOCALAPPDATA", home / "AppData" / "Local"))
        root = local / "Quest APK Renamer"
        return AppPaths(data=root, cache=root / "cache")

    if system == "darwin":
        data = home / "Library" / "Application Support" / "Quest APK Renamer"
        cache = home / "Library" / "Caches" / "Quest APK Renamer"
        return AppPaths(data=data, cache=cache)

    data_base = Path(environment.get("XDG_DATA_HOME", home / ".local" / "share"))
    cache_base = Path(environment.get("XDG_CACHE_HOME", home / ".cache"))
    return AppPaths(
        data=data_base / "quest-apk-renamer",
        cache=cache_base / "quest-apk-renamer",
    )
