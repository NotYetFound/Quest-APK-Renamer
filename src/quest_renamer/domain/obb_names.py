"""Strict parsing and package rewriting for Android expansion-file names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.package_ids import is_valid_package_id

OBB_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
PRESERVED_OBB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.obb$", re.IGNORECASE)


class ObbNameError(ValueError):
    """An expansion filename is unsafe, ambiguous, or belongs to another app."""


@dataclass(frozen=True, slots=True)
class ObbFileName:
    kind: str
    tag: str
    package_name: str

    @property
    def filename(self) -> str:
        return f"{self.kind}.{self.tag}.{self.package_name}.obb"

    def renamed(self, package_name: str) -> str:
        if not is_valid_package_id(package_name):
            raise ObbNameError(f"The target package ID is invalid: {package_name}")
        return f"{self.kind}.{self.tag}.{package_name}.obb"


def parse_obb_filename(filename: str) -> ObbFileName | None:
    """Parse ``main|patch.<tag>.<package>.obb`` without changing its tag.

    The tag is commonly a numeric Android version, but Unreal games also use
    labels such as ``pakchunk0-Android_ASTC``. It is intentionally one dot-free
    path-safe segment; the remainder must be a valid Android package ID.
    """

    if not filename.lower().endswith(".obb"):
        return None
    stem = filename[:-4]
    parts = stem.split(".", 2)
    if len(parts) != 3:
        return None
    kind, tag, package_name = parts
    if kind.casefold() not in {"main", "patch"}:
        return None
    if OBB_TAG.fullmatch(tag) is None or not is_valid_package_id(package_name):
        return None
    return ObbFileName(kind.casefold(), tag, package_name)


def require_obb_filename(filename: str) -> ObbFileName:
    parsed = parse_obb_filename(filename)
    if parsed is None:
        raise ObbNameError(
            f"Unsupported OBB filename: {filename}. Expected "
            "main/patch.<version-or-chunk>.<package>.obb."
        )
    return parsed


def is_safe_preserved_obb(filename: str) -> bool:
    """Whether a package-folder asset OBB can be copied without renaming."""
    return bool(PRESERVED_OBB.fullmatch(filename))


def renamed_obb_filenames(
    sources: tuple[Path, ...],
    *,
    source_package: str,
    target_package: str,
) -> tuple[str, ...]:
    """Validate and rewrite a complete OBB set without destination collisions."""

    names: list[str] = []
    seen: dict[str, str] = {}
    for source in sources:
        parsed = parse_obb_filename(source.name)
        if parsed is None:
            if not is_safe_preserved_obb(source.name):
                raise ObbNameError(
                    f"Unsupported OBB filename: {source.name}. Expected a safe asset name "
                    "or main/patch.<version-or-chunk>.<package>.obb."
                )
            renamed = source.name
        else:
            if (
                source_package
                and parsed.package_name.casefold() != source_package.casefold()
            ):
                raise ObbNameError(
                    f"OBB {source.name} belongs to {parsed.package_name}, "
                    f"not {source_package}."
                )
            renamed = parsed.renamed(target_package)
        normalized = renamed.casefold()
        if previous := seen.get(normalized):
            raise ObbNameError(
                "Multiple source OBB files would overwrite the same output file: "
                f"{previous} and {source.name} → {renamed}"
            )
        seen[normalized] = source.name
        names.append(renamed)
    return tuple(names)
