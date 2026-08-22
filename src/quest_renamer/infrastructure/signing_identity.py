"""Persistent per-install signing identity managed through Java keytool."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.process_runner import ProcessRunner


@dataclass(frozen=True, slots=True)
class SigningIdentity:
    keystore: Path
    metadata: Path
    alias: str
    password: str


class SigningIdentityError(RuntimeError):
    pass


DEFAULT_KEY_DNAME = "CN=Quest APK Renamer, OU=Local Build, O=Local, L=Local, ST=Local, C=US"
LINEAGE_KEY_DIR_NAME = "lineage-keys"
KEYSTORE_NAME = "quest-renamer.p12"
METADATA_NAME = "identity.json"
MIGRATION_ERROR_NAME = "legacy-migration-error.txt"
# Folders and files the app itself writes next to the identity; their presence
# never means a key pair is damaged or half-migrated.
AUXILIARY_SIGNING_ENTRIES = frozenset(
    {
        LINEAGE_KEY_DIR_NAME,
        "app-icons",
        "imported-identities",
        "backup-status.json",
        "backup-status.tmp",
        ".DS_Store",
        "Thumbs.db",
    }
)


def signing_identity_is_incomplete(root: Path) -> bool:
    """True when ``root`` holds a partial identity or a failed migration marker.

    A missing identity (no key, no metadata) is not incomplete — it is simply not
    created yet — unless the folder also holds a migration error or stray key-like
    files that the app did not create itself.
    """
    keystore = root / KEYSTORE_NAME
    metadata = root / METADATA_NAME
    if keystore.is_file() and metadata.is_file():
        return False
    if keystore.exists() or metadata.exists():
        return True
    if not root.is_dir():
        return False
    try:
        for entry in root.iterdir():
            if entry.name in AUXILIARY_SIGNING_ENTRIES:
                continue
            if entry.name.startswith(".") and entry.is_dir():
                # Staging folders from interrupted restores are cleaned separately.
                continue
            return True
    except OSError:
        return False
    return False


class SigningIdentityStore:
    def __init__(self, root: Path, keytool: Path, runner: ProcessRunner | None = None) -> None:
        self.root = root
        self.keytool = keytool
        self.runner = runner or ProcessRunner()
        self.keystore = root / KEYSTORE_NAME
        self.metadata = root / METADATA_NAME

    def load_or_create(
        self,
        *,
        token: CancellationToken,
        log: Callable[[str], None] | None = None,
        dname: str | None = None,
    ) -> SigningIdentity:
        # Keep the canonical identity available for ordinary builds and backups
        # even when the first APK happens to use a lineage-specific certificate.
        if dname and not (self.keystore.is_file() and self.metadata.is_file()):
            self.load_or_create(token=token, log=log)
        keystore, metadata = self._paths_for_dname(dname)
        if keystore.is_file() and metadata.is_file():
            return self._load(keystore, metadata)
        if not dname and signing_identity_is_incomplete(self.root):
            raise SigningIdentityError(
                "The signing identity is incomplete. Restore its key files or review the "
                "legacy-key migration error in the activity log before building."
            )
        if keystore.exists() or metadata.exists():
            raise SigningIdentityError(
                "The signing identity is incomplete. Restore both key files or remove the "
                "incomplete identity from the app data folder."
            )

        keystore.parent.mkdir(parents=True, exist_ok=True)
        alias = "quest-renamer"
        password = secrets.token_urlsafe(24)
        if log:
            log(
                "Creating a persistent signing identity with source lineage."
                if dname
                else "Creating a persistent local signing identity."
            )
        self.runner.run(
            (
                self.keytool,
                "-genkeypair",
                "-noprompt",
                "-keystore",
                keystore,
                "-storetype",
                "PKCS12",
                "-storepass",
                password,
                "-keypass",
                password,
                "-alias",
                alias,
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-dname",
                dname or DEFAULT_KEY_DNAME,
            ),
            token=token,
            log=log,
            secret_values={password},
        )
        temporary = metadata.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "alias": alias,
                    "password": password,
                    **({"dname": dname} if dname else {}),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, metadata)
        self._restrict_permissions(keystore, metadata)
        return SigningIdentity(keystore, metadata, alias, password)

    def _paths_for_dname(self, dname: str | None) -> tuple[Path, Path]:
        if not dname or dname == DEFAULT_KEY_DNAME:
            return self.keystore, self.metadata
        digest = hashlib.sha256(dname.encode("utf-8")).hexdigest()[:16]
        lineage_root = self.root / LINEAGE_KEY_DIR_NAME
        return (
            lineage_root / f"signing-{digest}.p12",
            lineage_root / f"signing-{digest}.json",
        )

    def load_existing(self, keystore: Path, metadata: Path) -> SigningIdentity:
        if not keystore.is_file() or not metadata.is_file():
            raise SigningIdentityError(
                "The saved signing key is incomplete. Restore its key and JSON files."
            )
        return self._load(keystore, metadata)

    def _load(self, keystore: Path, metadata: Path) -> SigningIdentity:
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            alias = payload["alias"]
            password = payload["password"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SigningIdentityError(
                f"The signing identity metadata is invalid: {exc}"
            ) from exc
        if (
            not isinstance(alias, str)
            or not alias
            or not isinstance(password, str)
            or not password
        ):
            raise SigningIdentityError("The signing identity metadata is incomplete.")
        self._restrict_permissions(keystore, metadata)
        return SigningIdentity(keystore, metadata, alias, password)

    @staticmethod
    def _restrict_permissions(*paths: Path) -> None:
        # Windows applies ACLs rather than POSIX modes; chmod remains harmless there.
        if os.name != "nt":
            mode = stat.S_IRUSR | stat.S_IWUSR
            for path in paths:
                os.chmod(path, mode)
