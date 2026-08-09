"""Application settings with explicit defaults and safe deserialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class AppSettings:
    copy_obbs: bool = True
    sign_apks: bool = True
    older_firmware_patch: bool = False
    delete_source_after_install: bool = False
    replace_source_after_build: bool = False
    automatic_preflight: bool = True
    check_updates: bool = True
    key_backup_reminder: bool = True
    key_backup_folder: str = ""
    dismissed_update: str = ""

    @classmethod
    def from_mapping(cls, values: object) -> AppSettings:
        if not isinstance(values, dict):
            return cls()
        defaults = cls()
        clean: dict[str, Any] = {}
        for name, default in defaults.to_mapping().items():
            value = values.get(name)
            clean[name] = value if isinstance(value, type(default)) else default
        return cls(**clean)

    def to_mapping(self) -> dict[str, bool | str]:
        return asdict(self)

    def with_value(self, name: str, value: Any) -> AppSettings:
        if name not in self.to_mapping():
            raise KeyError(name)
        current = getattr(self, name)
        if not isinstance(value, type(current)):
            expected = "a boolean" if isinstance(current, bool) else "text"
            raise TypeError(f"{name} must be {expected}")
        return replace(self, **{name: value})
