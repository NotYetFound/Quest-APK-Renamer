"""Auditable replacement of an existing ARM64 Oculus platform loader."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.toolchain import sha256_file

PATCH_ID = "older-firmware-compatibility"
LOADER_RELATIVE = Path("lib/arm64-v8a/libovrplatformloader.so")
LOADER_SHA256 = "1f6d43e6b7b82960efdaf6596953272c32022316375ddca1eddc56e15b026ca2"


class OlderFirmwarePatchError(RuntimeError):
    pass


def verified_older_firmware_asset(path: Path | None) -> Path | None:
    if path is None or not path.is_file():
        return None
    try:
        return path if sha256_file(path) == LOADER_SHA256 else None
    except OSError:
        return None


def _sha256(path: Path, token: CancellationToken) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            token.raise_if_cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def apply_older_firmware_patch(
    decoded: Path,
    replacement: Path | None,
    *,
    token: CancellationToken,
    log: Callable[[str], None] | None = None,
) -> None:
    if replacement is None or not replacement.is_file():
        raise OlderFirmwarePatchError(
            "The verified older-firmware patch asset is not installed."
        )
    if _sha256(replacement, token) != LOADER_SHA256:
        raise OlderFirmwarePatchError("The older-firmware patch failed its integrity check.")
    target = decoded / LOADER_RELATIVE
    if not target.is_file():
        raise OlderFirmwarePatchError(
            "This APK does not contain an ARM64 Oculus platform loader to replace."
        )
    shutil.copy2(replacement, target)
    if _sha256(target, token) != LOADER_SHA256:
        raise OlderFirmwarePatchError("The copied older-firmware patch could not be verified.")
    if log:
        log(
            "Applied the pinned Event Horizon older-firmware loader to "
            f"{LOADER_RELATIVE.as_posix()}."
        )
        log(f"Verified replacement SHA-256: {LOADER_SHA256}")
