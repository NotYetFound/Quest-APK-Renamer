"""Application settings with explicit defaults and safe deserialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
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
    # Remembered dialog start folders; purely a convenience, never required.
    last_source_folder: str = ""
    last_output_parent: str = ""
    # Suggested package-ID tag (without the leading dot) for newly selected games.
    default_tag: str = "dev"
    # Experimental: change the launcher name of renamed copies. Off by default and,
    # while off, nothing about it appears outside Settings.
    change_display_name: bool = False
    # Appended to the display name of every renamed copy ("(Dev)"); empty keeps it.
    label_suffix: str = ""
    # Legacy rename mode: move Java packages too. Refused for apps with JNI code.
    rename_java_packages: bool = False
    # Serial to use when more than one authorized device is attached.
    preferred_device_serial: str = ""
    # Last wireless ADB address (host:port) the user connected to.
    last_wireless_address: str = ""
    # Saved wireless Quests: ``[{"address": "host:port", "label": "Quest 3"}, ...]``.
    wireless_devices: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, values: object) -> AppSettings:
        if not isinstance(values, dict):
            return cls()
        defaults = cls()
        clean: dict[str, Any] = {}
        for name, default in defaults.to_mapping().items():
            value = values.get(name)
            if isinstance(default, list):
                clean[name] = _clean_device_list(value)
            else:
                clean[name] = value if isinstance(value, type(default)) else default
        return cls(**clean)

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    def with_value(self, name: str, value: Any) -> AppSettings:
        if name not in self.to_mapping():
            raise KeyError(name)
        current = getattr(self, name)
        if not isinstance(value, type(current)):
            expected = (
                "a boolean"
                if isinstance(current, bool)
                else "a list"
                if isinstance(current, list)
                else "text"
            )
            raise TypeError(f"{name} must be {expected}")
        if isinstance(value, list):
            value = _clean_device_list(value)
        return replace(self, **{name: value})

    def with_wireless_device(
        self,
        address: str,
        label: str = "",
        *,
        last_connected: str | None = None,
    ) -> AppSettings:
        """Add or update one saved wireless Quest, keeping the most recent first."""
        address = address.strip()
        if not address:
            return self
        existing = next(
            (item for item in self.wireless_devices if item["address"] == address), None
        )
        entry = {
            "address": address,
            "label": label.strip() or (existing["label"] if existing else ""),
            "last_connected": (
                last_connected
                if last_connected is not None
                else (existing.get("last_connected", "") if existing else "")
            ),
        }
        others = [item for item in self.wireless_devices if item["address"] != address]
        return replace(self, wireless_devices=[entry, *others][:12])

    def without_wireless_device(self, address: str) -> AppSettings:
        kept = [item for item in self.wireless_devices if item["address"] != address.strip()]
        return replace(self, wireless_devices=kept)


def _clean_device_list(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        address = str(item.get("address", "")).strip()
        if not address or address in seen:
            continue
        seen.add(address)
        clean.append(
            {
                "address": address,
                "label": str(item.get("label", "")).strip(),
                "last_connected": str(item.get("last_connected", "")).strip(),
            }
        )
    return clean
