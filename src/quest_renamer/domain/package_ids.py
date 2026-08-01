"""Android package-ID validation and deterministic suggestions."""

from __future__ import annotations

import re

PACKAGE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
TAG = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


def is_valid_package_id(value: str) -> bool:
    return bool(PACKAGE_ID.fullmatch(value.strip()))


def with_tag(package_name: str, tag: str = "dev") -> str:
    """Insert a separate tag segment without changing the publisher root."""
    package_name = package_name.strip()
    tag = tag.strip().lower().lstrip(".")
    if not is_valid_package_id(package_name):
        raise ValueError("The source package ID is invalid.")
    if not TAG.fullmatch(tag):
        raise ValueError("Tags must start with a letter and use 1-16 characters.")
    parts = package_name.split(".")
    if parts[1].lower() == tag:
        return package_name
    parts.insert(1, tag)
    return ".".join(parts)


def package_id_error(value: str, source: str = "") -> str:
    value = value.strip()
    if not value:
        return "Enter a package ID."
    if not is_valid_package_id(value):
        return "Use dot-separated words containing only letters, numbers, and underscores."
    if source and value == source.strip():
        return "Choose a different ID so Quest treats this as a separate app."
    return ""
