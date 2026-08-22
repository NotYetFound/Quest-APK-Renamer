"""Portable, validated archives for saved package IDs and signing identities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from quest_renamer.domain.library import GameProfile, profile_id
from quest_renamer.domain.package_ids import is_valid_package_id

ARCHIVE_FORMAT = 1
ARCHIVE_SUFFIX = ".qarlib"
MANIFEST_NAME = "library.json"
MAX_PROFILES = 5000
MAX_TOTAL_SIZE = 128 * 1024 * 1024
MAX_ARTIFACT_SIZE = 32 * 1024 * 1024
MAX_MANIFEST_SIZE = 8 * 1024 * 1024


class LibraryArchiveError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LibraryArchiveSummary:
    count: int
    names: tuple[str, ...]
    replacements: int = 0
    complete_keys: int = 0


@dataclass(frozen=True, slots=True)
class _ArchiveItem:
    profile: GameProfile
    artifacts: dict[str, bytes]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact_name(profile: GameProfile, kind: str, source: Path) -> str:
    suffix = source.suffix.lower() if kind == "icon" else ""
    if kind == "icon" and not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".img"
    filename = {
        "keystore": "signing-key.p12",
        "metadata": "identity.json",
        "icon": f"app-icon{suffix}",
    }[kind]
    return f"identities/{profile.id}/{filename}"


def _portable_entry(profile: GameProfile) -> tuple[dict[str, object], dict[str, bytes]]:
    files: dict[str, dict[str, str | int]] = {}
    artifacts: dict[str, bytes] = {}
    for kind, raw_path in (
        ("keystore", profile.signing_keystore),
        ("metadata", profile.signing_metadata),
        ("icon", profile.app_icon),
    ):
        if not raw_path:
            continue
        source = Path(raw_path)
        try:
            if not source.is_file() or source.stat().st_size > MAX_ARTIFACT_SIZE:
                continue
            data = source.read_bytes()
        except OSError:
            continue
        archive_name = _artifact_name(profile, kind, source)
        artifacts[archive_name] = data
        files[kind] = {
            "path": archive_name,
            "size": len(data),
            "sha256": _sha256(data),
        }
    return {"profile": profile.to_mapping(), "files": files}, artifacts


def export_library_archive(destination: Path, profiles: tuple[GameProfile, ...]) -> Path:
    if not profiles:
        raise LibraryArchiveError("There are no saved identities to export.")
    if len(profiles) > MAX_PROFILES:
        raise LibraryArchiveError("The Library contains too many identities to export safely.")
    destination = destination.expanduser().resolve(strict=False)
    if destination.suffix.casefold() != ARCHIVE_SUFFIX:
        destination = destination.with_suffix(ARCHIVE_SUFFIX)
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    artifacts: dict[str, bytes] = {}
    for profile in profiles:
        entry, profile_artifacts = _portable_entry(profile)
        entries.append(entry)
        artifacts.update(profile_artifacts)
    if sum(len(data) for data in artifacts.values()) > MAX_TOTAL_SIZE:
        raise LibraryArchiveError("The private files are too large to export safely.")
    manifest = {
        "format": ARCHIVE_FORMAT,
        "application": "Quest APK Renamer",
        "created_utc": datetime.now(UTC).isoformat(),
        "identities": entries,
    }
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    published = False
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            )
            for name, data in artifacts.items():
                archive.writestr(name, data)
        with suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, destination)
        published = True
        return destination
    except (OSError, zipfile.BadZipFile) as exc:
        raise LibraryArchiveError(f"The Library archive could not be exported: {exc}") from exc
    finally:
        if not published:
            temporary.unlink(missing_ok=True)


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name and not path.is_absolute() and ".." not in path.parts)


def _read_artifact(
    archive: zipfile.ZipFile,
    raw: object,
    *,
    expected_prefix: str,
) -> bytes:
    if not isinstance(raw, dict):
        raise LibraryArchiveError("An archived identity contains invalid file metadata.")
    name = raw.get("path")
    size = raw.get("size")
    digest = raw.get("sha256")
    if (
        not isinstance(name, str)
        or not name.startswith(expected_prefix)
        or not _safe_member(name)
        or not isinstance(size, int)
        or size < 0
        or size > MAX_ARTIFACT_SIZE
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise LibraryArchiveError("An archived identity contains unsafe file metadata.")
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise LibraryArchiveError(f"The archive is missing {name}.") from exc
    if info.file_size != size or info.file_size > MAX_ARTIFACT_SIZE:
        raise LibraryArchiveError(f"The archived file size is invalid: {name}")
    data = archive.read(info)
    if len(data) != size or _sha256(data) != digest:
        raise LibraryArchiveError(f"The archived file failed verification: {name}")
    return data


def _load_archive(source: Path) -> tuple[_ArchiveItem, ...]:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise LibraryArchiveError("Choose an existing Quest APK Renamer Library archive.")
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if any(not _safe_member(info.filename) for info in infos):
                raise LibraryArchiveError("The archive contains an unsafe path.")
            if sum(info.file_size for info in infos) > MAX_TOTAL_SIZE:
                raise LibraryArchiveError("The Library archive is too large to import safely.")
            manifest_info = archive.getinfo(MANIFEST_NAME)
            if manifest_info.file_size > MAX_MANIFEST_SIZE:
                raise LibraryArchiveError("The Library archive manifest is too large.")
            payload: Any = json.loads(archive.read(manifest_info).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("format") != ARCHIVE_FORMAT:
                raise LibraryArchiveError("This Library archive format is not supported.")
            identities = payload.get("identities")
            if not isinstance(identities, list) or not 1 <= len(identities) <= MAX_PROFILES:
                raise LibraryArchiveError("The Library archive contains no valid identities.")
            items: list[_ArchiveItem] = []
            seen: set[str] = set()
            for raw_entry in identities:
                if not isinstance(raw_entry, dict):
                    raise LibraryArchiveError(
                        "The Library archive contains an invalid identity."
                    )
                profile = GameProfile.from_mapping(raw_entry.get("profile"))
                if (
                    profile is None
                    or not is_valid_package_id(profile.original_package)
                    or not is_valid_package_id(profile.target_package)
                    or profile.id
                    != profile_id(profile.original_package, profile.target_package)
                    or profile.id in seen
                ):
                    raise LibraryArchiveError(
                        "The Library archive contains an invalid identity."
                    )
                seen.add(profile.id)
                files = raw_entry.get("files", {})
                if not isinstance(files, dict):
                    raise LibraryArchiveError(
                        "The Library archive contains invalid file records."
                    )
                prefix = f"identities/{profile.id}/"
                artifacts = {
                    kind: _read_artifact(archive, record, expected_prefix=prefix)
                    for kind in ("keystore", "metadata", "icon")
                    if (record := files.get(kind)) is not None
                }
                metadata = artifacts.get("metadata")
                if metadata is not None:
                    try:
                        metadata_payload = json.loads(metadata.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise LibraryArchiveError(
                            f"Signing metadata is invalid for {profile.game_name}."
                        ) from exc
                    if not isinstance(metadata_payload, dict):
                        raise LibraryArchiveError(
                            f"Signing metadata is invalid for {profile.game_name}."
                        )
                items.append(_ArchiveItem(profile, artifacts))
            return tuple(items)
    except LibraryArchiveError:
        raise
    except (
        OSError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        raise LibraryArchiveError(f"The selected Library archive is invalid: {exc}") from exc


def inspect_library_archive(
    source: Path,
    existing_ids: set[str] | None = None,
) -> LibraryArchiveSummary:
    items = _load_archive(source)
    existing = existing_ids or set()
    return LibraryArchiveSummary(
        len(items),
        tuple(item.profile.game_name for item in items),
        sum(item.profile.id in existing for item in items),
        sum(
            "keystore" in item.artifacts and "metadata" in item.artifacts
            for item in items
        ),
    )


def import_library_archive(source: Path, signing_root: Path) -> tuple[GameProfile, ...]:
    items = _load_archive(source)
    imported_root = signing_root / "imported-identities"
    try:
        imported_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LibraryArchiveError(
            f"The imported-key folder could not be created: {exc}"
        ) from exc
    profiles: list[GameProfile] = []
    for item in items:
        folder = imported_root / f"{item.profile.id}-{uuid.uuid4().hex[:10]}"
        folder.mkdir(mode=0o700)
        paths: dict[str, str] = {}
        try:
            for kind, data in item.artifacts.items():
                filename = {
                    "keystore": "signing-key.p12",
                    "metadata": "identity.json",
                    "icon": "app-icon.img",
                }[kind]
                destination = folder / filename
                destination.write_bytes(data)
                if kind in {"keystore", "metadata"}:
                    with suppress(OSError):
                        destination.chmod(0o600)
                paths[kind] = str(destination)
        except OSError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise LibraryArchiveError(
                f"Files for {item.profile.game_name} could not be imported: {exc}"
            ) from exc
        keystore = item.artifacts.get("keystore")
        profiles.append(
            replace(
                item.profile,
                signing_keystore=paths.get("keystore", ""),
                signing_metadata=paths.get("metadata", ""),
                signing_key_sha256=_sha256(keystore) if keystore is not None else "",
                app_icon=paths.get("icon", ""),
            )
        )
    return tuple(profiles)
