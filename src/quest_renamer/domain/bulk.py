"""Pure package-ID rules shared by the bulk workflow and its UI preview."""

from __future__ import annotations

import re

from quest_renamer.domain.package_ids import is_valid_package_id

SUFFIX = re.compile(r"^[A-Za-z0-9_]{1,24}$")


def package_with_suffix(package_name: str, suffix: str) -> str:
    """Append one short literal suffix to the final package segment."""
    package_name = package_name.strip()
    suffix = suffix.strip()
    if not is_valid_package_id(package_name):
        raise ValueError("The source package ID is invalid.")
    if not SUFFIX.fullmatch(suffix):
        raise ValueError("Use 1-24 letters, numbers, or underscores.")
    result = package_name + suffix
    if not is_valid_package_id(result):
        raise ValueError("That suffix would create an invalid package ID.")
    return result
