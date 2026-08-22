"""Atomic JSON persistence for user-controlled defaults."""

from __future__ import annotations

from pathlib import Path

from quest_renamer.domain.settings import AppSettings
from quest_renamer.infrastructure.json_state import RecoveringJsonFile


class JsonSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._state = RecoveringJsonFile(path, label="Settings")

    @property
    def warning(self) -> str:
        return self._state.warning

    @property
    def recovery_path(self) -> Path | None:
        return self._state.recovery_path

    def load(self) -> AppSettings:
        loaded = self._state.load(
            lambda payload: AppSettings.from_mapping(payload)
            if isinstance(payload, dict)
            else None
        )
        return loaded or AppSettings()

    def save(self, settings: AppSettings) -> None:
        self._state.save(settings.to_mapping())
