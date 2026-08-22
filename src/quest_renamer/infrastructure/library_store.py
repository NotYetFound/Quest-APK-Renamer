"""Atomic, portable JSON persistence for the automatic game library."""

from __future__ import annotations

from pathlib import Path

from quest_renamer.domain.library import GameProfile
from quest_renamer.infrastructure.json_state import RecoveringJsonFile


class GameLibraryStore:
    FORMAT = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self._state = RecoveringJsonFile(path, label="Game Library")

    @property
    def warning(self) -> str:
        return self._state.warning

    @property
    def recovery_path(self) -> Path | None:
        return self._state.recovery_path

    def load(self) -> tuple[GameProfile, ...]:
        loaded = self._state.load(self._parse)
        return loaded or ()

    def _parse(self, payload: object) -> tuple[GameProfile, ...] | None:
        if not isinstance(payload, dict) or payload.get("format") != self.FORMAT:
            return None
        games = payload.get("games")
        if not isinstance(games, list):
            return None
        profiles = tuple(
            profile for item in games if (profile := GameProfile.from_mapping(item)) is not None
        )
        if len(profiles) != len(games):
            return None
        return tuple(sorted(profiles, key=lambda item: item.updated_utc, reverse=True))

    def save(self, profiles: tuple[GameProfile, ...]) -> None:
        self._state.save(
            {
                "format": self.FORMAT,
                "games": [profile.to_mapping() for profile in profiles],
            }
        )

    def upsert(self, profile: GameProfile) -> tuple[GameProfile, ...]:
        profiles = list(self.load())
        for index, current in enumerate(profiles):
            if current.id == profile.id:
                profiles[index] = profile
                break
        else:
            profiles.append(profile)
        result = tuple(sorted(profiles, key=lambda item: item.updated_utc, reverse=True))
        self.save(result)
        return result

    def forget(self, profile_id: str) -> tuple[GameProfile, ...]:
        profiles = tuple(item for item in self.load() if item.id != profile_id)
        self.save(profiles)
        return profiles
