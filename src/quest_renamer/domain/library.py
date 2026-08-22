"""Persistent game profiles used to make repeat updates automatic."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def profile_id(original_package: str, target_package: str) -> str:
    """Return a stable, non-secret identifier for one renamed game identity."""
    value = f"{original_package}\0{target_package}".encode()
    return hashlib.sha256(value).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class LibraryObb:
    name: str
    size: int
    sha256: str = ""

    @classmethod
    def from_mapping(cls, value: object) -> LibraryObb | None:
        if not isinstance(value, dict):
            return None
        name = value.get("name")
        size = value.get("size")
        sha256 = value.get("sha256", "")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
        ):
            return None
        return cls(name, size, sha256)

    def to_mapping(self) -> dict[str, str | int]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class GameProfile:
    id: str
    game_name: str
    original_package: str
    target_package: str
    app_icon: str = ""
    source_path: str = ""
    output_path: str = ""
    source_version: str = ""
    source_signer_id: str = ""
    installed_version: str = ""
    signing_keystore: str = ""
    signing_metadata: str = ""
    signing_key_sha256: str = ""
    patches: tuple[str, ...] = ()
    obbs: tuple[LibraryObb, ...] = ()
    last_device_serial: str = ""
    created_utc: str = ""
    updated_utc: str = ""

    @classmethod
    def create(
        cls,
        *,
        game_name: str,
        original_package: str,
        target_package: str,
        **values: Any,
    ) -> GameProfile:
        now = _now()
        return cls(
            profile_id(original_package, target_package),
            game_name or target_package,
            original_package,
            target_package,
            created_utc=now,
            updated_utc=now,
            **values,
        )

    @classmethod
    def from_mapping(cls, value: object) -> GameProfile | None:
        if not isinstance(value, dict):
            return None
        required = ("id", "game_name", "original_package", "target_package")
        if not all(isinstance(value.get(name), str) and value[name] for name in required):
            return None
        strings = (
            "app_icon",
            "source_path",
            "output_path",
            "source_version",
            "source_signer_id",
            "installed_version",
            "signing_keystore",
            "signing_metadata",
            "signing_key_sha256",
            "last_device_serial",
            "created_utc",
            "updated_utc",
        )
        clean_strings = {
            name: raw if isinstance((raw := value.get(name, "")), str) else ""
            for name in strings
        }
        patches_raw = value.get("patches", [])
        patches = (
            tuple(item for item in patches_raw if isinstance(item, str))
            if isinstance(patches_raw, list)
            else ()
        )
        obbs_raw = value.get("obbs", [])
        obbs = (
            tuple(
                parsed
                for item in obbs_raw
                if (parsed := LibraryObb.from_mapping(item)) is not None
            )
            if isinstance(obbs_raw, list)
            else ()
        )
        return cls(
            id=value["id"],
            game_name=value["game_name"],
            original_package=value["original_package"],
            target_package=value["target_package"],
            patches=patches,
            obbs=obbs,
            **clean_strings,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "id": self.id,
            "game_name": self.game_name,
            "original_package": self.original_package,
            "target_package": self.target_package,
            "app_icon": self.app_icon,
            "source_path": self.source_path,
            "output_path": self.output_path,
            "source_version": self.source_version,
            "source_signer_id": self.source_signer_id,
            "installed_version": self.installed_version,
            "signing_keystore": self.signing_keystore,
            "signing_metadata": self.signing_metadata,
            "signing_key_sha256": self.signing_key_sha256,
            "patches": list(self.patches),
            "obbs": [obb.to_mapping() for obb in self.obbs],
            "last_device_serial": self.last_device_serial,
            "created_utc": self.created_utc,
            "updated_utc": self.updated_utc,
        }

    def updated(self, **values: Any) -> GameProfile:
        return replace(self, updated_utc=_now(), **values)

    @property
    def key_available(self) -> bool:
        if not self.signing_keystore or not self.signing_metadata:
            return False
        keystore = Path(self.signing_keystore)
        metadata = Path(self.signing_metadata)
        if not keystore.is_file() or not metadata.is_file():
            return False
        if not self.signing_key_sha256:
            return True
        try:
            return hashlib.sha256(keystore.read_bytes()).hexdigest() == self.signing_key_sha256
        except OSError:
            return False
