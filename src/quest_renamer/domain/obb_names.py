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
        return self.renamed(self.package_name)

    def renamed(self, package_name: str) -> str:
        if not is_valid_package_id(package_name):
            raise ObbNameError(f"The target package ID is invalid: {package_name}")
        if self.tag:
            return f"{self.kind}.{self.tag}.{package_name}.obb"
        return f"{self.kind}.{package_name}.obb"


def _is_version_tag(tag: str) -> bool:
    return OBB_TAG.fullmatch(tag) is not None and not tag.isalpha()


def parse_obb_filename(filename: str, expected_package: str = "") -> ObbFileName | None:
    """Parse ``main|patch[.<tag>].<package>.obb`` without changing its tag.

    The tag is commonly a numeric Android version, but Unreal games also use
    labels such as ``pakchunk0-Android_ASTC``, and some games ship a tag-less
    ``patch.<package>.obb``. The tag is intentionally one dot-free path-safe
    segment; the remainder must be a valid Android package ID.

    ``patch.com.example.game.obb`` is ambiguous on its own (tag ``com`` for package
    ``example.game``, or no tag for ``com.example.game``). When the owning package
    is known, the reading that matches it wins; otherwise a purely alphabetic
    "tag" is taken as the first package segment, because real version tags
    contain digits.
    """

    if not filename.lower().endswith(".obb"):
        return None
    stem = filename[:-4]
    kind, _separator, rest = stem.partition(".")
    if kind.casefold() not in {"main", "patch"} or not rest:
        return None
    kind = kind.casefold()
    tag, tag_separator, package_name = rest.partition(".")
    tagged = (
        ObbFileName(kind, tag, package_name)
        if tag_separator
        and OBB_TAG.fullmatch(tag) is not None
        and is_valid_package_id(package_name)
        else None
    )
    untagged = ObbFileName(kind, "", rest) if is_valid_package_id(rest) else None
    if expected_package:
        wanted = expected_package.casefold()
        for candidate in (tagged, untagged):
            if candidate is not None and candidate.package_name.casefold() == wanted:
                return candidate
    if tagged is not None and untagged is not None and not _is_version_tag(tag):
        return untagged
    return tagged or untagged


def require_obb_filename(filename: str) -> ObbFileName:
    parsed = parse_obb_filename(filename)
    if parsed is None:
        raise ObbNameError(
            f"Unsupported OBB filename: {filename}. Expected "
            "main/patch[.<version-or-chunk>].<package>.obb."
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
        parsed = parse_obb_filename(source.name, source_package)
        if parsed is None:
            if not is_safe_preserved_obb(source.name):
                raise ObbNameError(
                    f"Unsupported OBB filename: {source.name}. Expected a safe asset name "
                    "or main/patch[.<version-or-chunk>].<package>.obb."
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
