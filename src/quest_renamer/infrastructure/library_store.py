"""Atomic, portable JSON persistence for the automatic game library."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from quest_renamer.domain.library import GameProfile


class GameLibraryStore:
    FORMAT = 1

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[GameProfile, ...]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ()
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, dict) or payload.get("format") != self.FORMAT:
            return ()
        games = payload.get("games")
        if not isinstance(games, list):
            return ()
        profiles = tuple(
            profile for item in games if (profile := GameProfile.from_mapping(item)) is not None
        )
        return tuple(sorted(profiles, key=lambda item: item.updated_utc, reverse=True))

    def save(self, profiles: tuple[GameProfile, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "format": self.FORMAT,
                    "games": [profile.to_mapping() for profile in profiles],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, self.path)

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
