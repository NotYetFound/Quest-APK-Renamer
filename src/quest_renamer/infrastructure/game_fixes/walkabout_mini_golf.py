"""Walkabout Mini Golf: keep the expansion files working after a rename.

Walkabout Mini Golf (``com.MightyCoconut.WalkaboutMiniGolf``) keeps its content
in an OBB expansion file, and two places outside Android's own manifest and code
references name the package:

* the Unity Addressables catalog in the OBB (``assets/aa/catalog.bin``) stores
  the package as a shared path segment of many internal IDs;
* the repack ships a JSON ``lib/<abi>/libfrda.config.so`` naming the OBB file
  (``main.<tag>.<package>.obb``).

Leaving those alone gives a renamed copy that installs but cannot open its
content. This fix rewrites exactly those references and refuses any layout it
does not fully understand. It runs only for the source package listed below.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.infrastructure.addressables_catalog import (
    CATALOG_ENTRY,
    AddressablesCatalogError,
    rewrite_catalog_paths,
)
from quest_renamer.infrastructure.game_fixes.base import (
    DecodedApkFixResult,
    GameFixContext,
    GameFixError,
)
from quest_renamer.infrastructure.zip_stored_entry import (
    ZipStoredEntryError,
    rewrite_stored_entry,
)

SOURCE_PACKAGE = "com.MightyCoconut.WalkaboutMiniGolf"
CONFIG_GLOB = "lib/*/libfrda.config.so"
_MAX_CONFIG_SIZE = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ObbCatalogRewrite:
    entry: str
    repointed_records: int
    internal_ids: int
    size_delta: int


class WalkaboutMiniGolfFix:
    fix_id = "walkabout-mini-golf-expansion-paths"
    title = "Walkabout Mini Golf expansion-file paths"
    source_packages = frozenset({SOURCE_PACKAGE})

    def apply_to_decoded_apk(
        self, context: GameFixContext, decoded: Path
    ) -> DecodedApkFixResult:
        files = rewrite_decoded_config(decoded, context)
        return DecodedApkFixResult(
            rewritten_files=files,
            report=tuple(
                f"APK {entry}: expansion-file path now points at "
                f"{context.new_package}."
                for entry in files
            ),
        )

    def apply_to_obb(self, context: GameFixContext, obb_path: Path) -> tuple[str, ...]:
        rewrite = rewrite_obb_catalog(obb_path, context)
        if rewrite is None:
            return ()
        return (
            f"OBB {obb_path.name}: rewrote {rewrite.entry} "
            f"({rewrite.repointed_records} string record(s), "
            f"{rewrite.internal_ids} internal ID(s), "
            f"{rewrite.size_delta:+d} bytes).",
        )


def rewrite_decoded_config(decoded: Path, context: GameFixContext) -> tuple[str, ...]:
    """Rewrite the JSON expansion path inside a decoded APK; return the files."""
    old_package, new_package = context.old_package, context.new_package
    if old_package == new_package:
        return ()
    old = old_package.encode("ascii")
    new = new_package.encode("ascii")
    patched: list[str] = []
    for path in sorted(decoded.glob(CONFIG_GLOB)):
        context.token.raise_if_cancelled()
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(decoded).as_posix()
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise GameFixError(
                f"the expansion configuration {relative} could not be read ({exc})."
            ) from exc
        if size > _MAX_CONFIG_SIZE:
            raise GameFixError(
                f"the expansion configuration {relative} is unexpectedly large."
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise GameFixError(
                f"the expansion configuration {relative} could not be read ({exc})."
            ) from exc
        if data.startswith(b"\x7fELF"):
            context.log(
                f"Skipped {relative}: it is a native library, not the JSON "
                "expansion configuration."
            )
            continue
        occurrences = data.count(old)
        if not occurrences:
            continue
        if occurrences > 1:
            raise GameFixError(
                f"{relative} contains {occurrences} occurrences of {old_package!r}; "
                "exactly one expansion-file path is required."
            )
        index = data.find(old)
        quote_start = data.rfind(b'"', 0, index)
        quote_end = data.find(b'"', index + len(old))
        if quote_start < 0 or quote_end < 0:
            raise GameFixError(
                f"{relative} mentions {old_package!r} outside a quoted value."
            )
        raw_value = data[quote_start + 1 : quote_end]
        value = raw_value.rsplit(b"/", 1)[-1]
        if not re.fullmatch(
            rb"(?:main|patch)\.[A-Za-z0-9_.-]+\." + re.escape(old) + rb"\.obb", value
        ):
            raise GameFixError(
                f"{relative} mentions {old_package!r} outside an expansion-file path."
            )
        try:
            parsed = json.loads(data)
            expected_path = raw_value.decode("utf-8")
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise GameFixError(
                f"{relative} is not a valid JSON expansion configuration."
            ) from exc
        pending = [parsed]
        path_found = False
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                path_found = path_found or item.get("path") == expected_path
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        if not path_found:
            raise GameFixError(
                f"{relative} mentions the OBB outside a JSON expansion-file path field."
            )
        updated = data[:index] + new + data[index + len(old) :]
        try:
            path.write_bytes(updated)
        except OSError as exc:
            raise GameFixError(
                f"the expansion configuration {relative} could not be updated ({exc})."
            ) from exc
        patched.append(relative)
        context.log(f"Rewrote the expansion-file path in {relative}.")
    return tuple(patched)


def rewrite_obb_catalog(obb: Path, context: GameFixContext) -> ObbCatalogRewrite | None:
    """Rewrite the Addressables catalog inside an OBB file, in place."""
    old_package, new_package = context.old_package, context.new_package
    token = context.token
    if old_package == new_package:
        return None
    try:
        if not zipfile.is_zipfile(obb):
            with obb.open("rb") as handle:
                signature = handle.read(4)
            if signature in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}:
                raise GameFixError(f"{obb.name} is not a readable OBB archive.")
            return None
        with zipfile.ZipFile(obb) as archive:
            try:
                info = archive.getinfo(CATALOG_ENTRY)
            except KeyError:
                return None
            if info.compress_type != zipfile.ZIP_STORED:
                raise GameFixError(
                    f"{obb.name} stores {CATALOG_ENTRY} compressed; that layout is not "
                    "rewritten automatically."
                )
            catalog = archive.read(CATALOG_ENTRY)
    except zipfile.BadZipFile as exc:
        raise GameFixError(f"{obb.name} is not a readable OBB archive ({exc}).") from exc
    except (OSError, RuntimeError, NotImplementedError) as exc:
        raise GameFixError(
            f"the Addressables catalog in {obb.name} could not be read ({exc})."
        ) from exc
    token.raise_if_cancelled()
    try:
        patch = rewrite_catalog_paths(catalog, old_package, new_package)
        if patch is None:
            return None
        token.raise_if_cancelled()
        size_delta = rewrite_stored_entry(obb, CATALOG_ENTRY, patch.data, token=token)
    except (AddressablesCatalogError, ZipStoredEntryError) as exc:
        raise GameFixError(str(exc)) from exc
    rewrite = ObbCatalogRewrite(
        entry=CATALOG_ENTRY,
        repointed_records=patch.repointed_records,
        internal_ids=patch.internal_ids,
        size_delta=size_delta,
    )
    context.log(
        f"Rewrote {CATALOG_ENTRY} in {obb.name}: "
        f"{rewrite.repointed_records} string record(s), "
        f"{rewrite.internal_ids} internal ID(s), {rewrite.size_delta:+d} bytes."
    )
    return rewrite
