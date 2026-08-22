"""Atomic, cross-platform backup and restore for the persistent signing identity."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.domain.signing import (
    SigningBackupError,
    SigningBackupResult,
    SigningIdentityAlreadyExists,
    SigningRestoreResult,
    SigningState,
)
from quest_renamer.infrastructure.process_runner import CommandFailed, ProcessRunner
from quest_renamer.infrastructure.signing_identity import signing_identity_is_incomplete

KEYSTORE_NAME = "quest-renamer.p12"
METADATA_NAME = "identity.json"
MARKER_NAME = "backup-status.json"
LINEAGE_DIR_NAME = "lineage-keys"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _lineage_hashes(root: Path) -> dict[str, str]:
    lineage = root / LINEAGE_DIR_NAME
    if not lineage.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(lineage.iterdir())
        if path.is_file()
    }


def _unique_path(parent: Path, stem: str) -> Path:
    candidate = parent / stem
    number = 2
    while candidate.exists():
        candidate = parent / f"{stem}-{number}"
        number += 1
    return candidate


class SigningIdentityManager:
    def __init__(
        self,
        root: Path,
        *,
        keytool: Path | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.root = root
        self.keytool = keytool
        self.runner = runner or ProcessRunner()
        self.keystore = root / KEYSTORE_NAME
        self.metadata = root / METADATA_NAME
        self.marker = root / MARKER_NAME

    def state(self) -> SigningState:
        key_exists = self.keystore.is_file()
        metadata_exists = self.metadata.is_file()
        if not key_exists and not metadata_exists:
            if signing_identity_is_incomplete(self.root):
                return SigningState(
                    True,
                    False,
                    False,
                    "Incomplete identity — review the migration error before building",
                )
            return SigningState(
                False,
                False,
                False,
                "Created automatically when the first APK is signed",
            )
        if not key_exists or not metadata_exists:
            return SigningState(
                True,
                False,
                False,
                "Incomplete identity — restore a complete backup before building",
            )
        backed_up = self._marker_matches_identity()
        return SigningState(
            True,
            True,
            backed_up,
            "Ready • backup recorded" if backed_up else "Ready • backup recommended",
        )

    def backup_to(
        self,
        parent: Path,
        *,
        token: CancellationToken | None = None,
        log: Callable[[str], None] | None = None,
    ) -> SigningBackupResult:
        token = token or CancellationToken()
        parent = parent.expanduser().resolve()
        if not parent.is_dir():
            raise SigningBackupError("Choose an existing folder for the backup.")
        if parent == self.root or self.root in parent.parents:
            raise SigningBackupError(
                "Choose a backup location outside the app's live signing folder."
            )
        self._validate_identity(self.root, token=token, log=log)
        token.raise_if_cancelled()
        destination = _unique_path(
            parent,
            f"Quest APK Renamer Signing Key Backup {_timestamp()}",
        )
        staging = Path(tempfile.mkdtemp(prefix=".quest-key-backup-", dir=parent))
        published = False
        try:
            shutil.copy2(self.keystore, staging / KEYSTORE_NAME)
            shutil.copy2(self.metadata, staging / METADATA_NAME)
            lineage_source = self.root / LINEAGE_DIR_NAME
            if lineage_source.is_dir():
                shutil.copytree(lineage_source, staging / LINEAGE_DIR_NAME)
            manifest = {
                "format": 2,
                "created_utc": datetime.now(UTC).isoformat(),
                "keystore_sha256": _sha256(staging / KEYSTORE_NAME),
                "metadata_sha256": _sha256(staging / METADATA_NAME),
                "lineage_sha256": _lineage_hashes(staging),
            }
            (staging / "backup.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )
            (staging / "README.txt").write_text(
                "Quest APK Renamer signing-key backup\n\n"
                "Keep this entire folder private and together. It contains the key and "
                "password needed to update apps signed with this identity.\n"
                "The lineage-keys folder contains identities that preserve recognized "
                "source-signer provenance. Keep it with the main key files.\n",
                encoding="utf-8",
            )
            self._restrict(staging / KEYSTORE_NAME, staging / METADATA_NAME)
            self._restrict(*(staging / path for path in _lineage_hashes(staging)))
            token.raise_if_cancelled()
            os.replace(staging, destination)
            published = True
            self._write_marker(destination)
            if log:
                log(f"Signing identity backed up to {destination}.")
            return SigningBackupResult(destination)
        except (OSError, CommandFailed, json.JSONDecodeError) as exc:
            raise SigningBackupError(f"The signing-key backup failed: {exc}") from exc
        finally:
            if not published:
                shutil.rmtree(staging, ignore_errors=True)

    def restore_from(
        self,
        source: Path,
        *,
        replace_existing: bool = False,
        token: CancellationToken | None = None,
        log: Callable[[str], None] | None = None,
    ) -> SigningRestoreResult:
        token = token or CancellationToken()
        source = source.expanduser().resolve()
        if source == self.root or self.root in source.parents:
            raise SigningBackupError(
                "Choose a separate backup folder, not the live signing folder."
            )
        self._validate_backup_manifest(source)
        self._validate_identity(source, token=token, log=log)
        current = self.state()
        if current.exists and not replace_existing:
            raise SigningIdentityAlreadyExists(
                "A signing identity already exists and must be confirmed before replacement."
            )
        self.root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{self.root.name}.restore-", dir=self.root.parent)
        )
        recovery: Path | None = None
        activated = False
        try:
            shutil.copy2(source / KEYSTORE_NAME, staging / KEYSTORE_NAME)
            shutil.copy2(source / METADATA_NAME, staging / METADATA_NAME)
            lineage_source = source / LINEAGE_DIR_NAME
            if lineage_source.is_dir():
                shutil.copytree(lineage_source, staging / LINEAGE_DIR_NAME)
            self._restrict(staging / KEYSTORE_NAME, staging / METADATA_NAME)
            self._restrict(*(staging / path for path in _lineage_hashes(staging)))
            self._validate_identity(staging, token=token, log=log)
            token.raise_if_cancelled()
            if self.root.exists():
                recovery = _unique_path(
                    self.root.parent,
                    f"{self.root.name}.previous-{_timestamp()}",
                )
                os.replace(self.root, recovery)
            try:
                os.replace(staging, self.root)
                activated = True
            except OSError:
                if recovery is not None and not self.root.exists():
                    os.replace(recovery, self.root)
                    recovery = None
                raise
            self._write_marker(source)
            if log:
                log(f"Signing identity restored from {source}.")
            return SigningRestoreResult(source, recovery)
        except SigningBackupError:
            raise
        except (OSError, CommandFailed, json.JSONDecodeError) as exc:
            raise SigningBackupError(f"The signing-key restore failed: {exc}") from exc
        finally:
            if not activated:
                shutil.rmtree(staging, ignore_errors=True)

    def _validate_identity(
        self,
        folder: Path,
        *,
        token: CancellationToken,
        log: Callable[[str], None] | None,
    ) -> None:
        keystore = folder / KEYSTORE_NAME
        metadata = folder / METADATA_NAME
        if not keystore.is_file() or not metadata.is_file():
            raise SigningBackupError(
                f"The selected folder must contain {KEYSTORE_NAME} and {METADATA_NAME}."
            )
        if keystore.stat().st_size == 0:
            raise SigningBackupError("The signing keystore is empty.")
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            alias = payload["alias"]
            password = payload["password"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SigningBackupError(f"The signing metadata is invalid: {exc}") from exc
        if not isinstance(alias, str) or not alias:
            raise SigningBackupError("The signing alias is missing.")
        if not isinstance(password, str) or not password:
            raise SigningBackupError("The signing password is missing.")
        token.raise_if_cancelled()
        if self.keytool is not None and self.keytool.is_file():
            self.runner.run(
                (
                    self.keytool,
                    "-list",
                    "-keystore",
                    keystore,
                    "-storetype",
                    "PKCS12",
                    "-storepass",
                    password,
                    "-alias",
                    alias,
                ),
                token=token,
                log=log,
                secret_values={password},
            )

    def _marker_matches_identity(self) -> bool:
        if not self.marker.is_file():
            return False
        try:
            payload = json.loads(self.marker.read_text(encoding="utf-8"))
            return bool(
                payload.get("keystore_sha256") == _sha256(self.keystore)
                and payload.get("metadata_sha256") == _sha256(self.metadata)
                and payload.get("lineage_sha256", {}) == _lineage_hashes(self.root)
            )
        except (OSError, json.JSONDecodeError):
            return False

    @staticmethod
    def _validate_backup_manifest(folder: Path) -> None:
        manifest = folder / "backup.json"
        if not manifest.is_file():
            raise SigningBackupError("The selected folder is not a complete key backup.")
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SigningBackupError(f"The backup manifest is invalid: {exc}") from exc
        if payload.get("format") not in {1, 2}:
            raise SigningBackupError("The signing-key backup format is not supported.")
        expected_key = payload.get("keystore_sha256")
        expected_metadata = payload.get("metadata_sha256")
        try:
            actual_key = _sha256(folder / KEYSTORE_NAME)
            actual_metadata = _sha256(folder / METADATA_NAME)
        except OSError as exc:
            raise SigningBackupError(f"The backup files could not be read: {exc}") from exc
        if expected_key != actual_key or expected_metadata != actual_metadata:
            raise SigningBackupError(
                "The signing-key backup failed its integrity check and was not restored."
            )
        expected_lineage = payload.get("lineage_sha256", {})
        if not isinstance(expected_lineage, dict) or not all(
            isinstance(name, str) and isinstance(digest, str)
            for name, digest in expected_lineage.items()
        ):
            raise SigningBackupError("The signing-key backup lineage manifest is invalid.")
        if expected_lineage != _lineage_hashes(folder):
            raise SigningBackupError(
                "The signing-key backup lineage files failed their integrity check."
            )

    def _write_marker(self, destination: Path) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "keystore_sha256": _sha256(self.keystore),
            "metadata_sha256": _sha256(self.metadata),
            "lineage_sha256": _lineage_hashes(self.root),
            "last_backup": str(destination),
            "recorded_utc": datetime.now(UTC).isoformat(),
        }
        temporary = self.marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.marker)
        if os.name != "nt":
            os.chmod(self.marker, stat.S_IRUSR | stat.S_IWUSR)

    @staticmethod
    def _restrict(*paths: Path) -> None:
        if os.name == "nt":
            return
        mode = stat.S_IRUSR | stat.S_IWUSR
        for path in paths:
            os.chmod(path, mode)
