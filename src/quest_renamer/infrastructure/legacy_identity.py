"""Safe one-time migration of signing identities created by the legacy app."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.process_runner import CommandFailed, ProcessRunner
from quest_renamer.infrastructure.signing_identity import AUXILIARY_SIGNING_ENTRIES

LEGACY_KEYSTORE_NAME = "quest-renamer-signing-key.jks"
LEGACY_METADATA_NAME = "signing-key.json"
MIGRATED_KEYSTORE_NAME = "quest-renamer.p12"
MIGRATED_METADATA_NAME = "identity.json"
MIGRATION_ERROR_NAME = "legacy-migration-error.txt"


class LegacyIdentityMigrationError(RuntimeError):
    pass


def migrate_legacy_signing_identity(
    app_data: Path,
    signing_root: Path,
    keytool: Path | None,
    *,
    runner: ProcessRunner | None = None,
    token: CancellationToken | None = None,
    log: Callable[[str], None] | None = None,
) -> bool:
    """Convert the legacy identity to the v1 PKCS12 layout without altering it."""

    destination_key = signing_root / MIGRATED_KEYSTORE_NAME
    destination_metadata = signing_root / MIGRATED_METADATA_NAME
    if destination_key.is_file() and destination_metadata.is_file():
        return False
    if signing_root.exists():
        error_marker = signing_root / MIGRATION_ERROR_NAME
        entries = tuple(
            entry
            for entry in signing_root.iterdir()
            if entry.name not in AUXILIARY_SIGNING_ENTRIES and entry != error_marker
        )
        if entries:
            return False
        error_marker.unlink(missing_ok=True)

    legacy_key = app_data / LEGACY_KEYSTORE_NAME
    legacy_metadata = app_data / LEGACY_METADATA_NAME
    if not legacy_key.exists() and not legacy_metadata.exists():
        return False
    if not legacy_key.is_file() or not legacy_metadata.is_file():
        raise LegacyIdentityMigrationError(
            "The previous signing identity is incomplete. Keep its .jks and JSON files "
            "together before upgrading."
        )
    if keytool is None or not keytool.is_file():
        raise LegacyIdentityMigrationError(
            "The previous signing identity was found, but Java keytool is unavailable."
        )

    try:
        payload = json.loads(legacy_metadata.read_text(encoding="utf-8"))
        alias = payload["alias"]
        password = payload["password"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise LegacyIdentityMigrationError(
            f"The previous signing identity metadata is invalid: {exc}"
        ) from exc
    if not isinstance(alias, str) or not alias or not isinstance(password, str) or not password:
        raise LegacyIdentityMigrationError(
            "The previous signing identity metadata is incomplete."
        )

    app_data.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".signing-migration-", dir=app_data))
    process_runner = runner or ProcessRunner()
    cancellation = token or CancellationToken()
    activated = False
    try:
        staged_key = staging / MIGRATED_KEYSTORE_NAME
        staged_metadata = staging / MIGRATED_METADATA_NAME
        if log:
            log("Migrating the existing Quest APK Renamer signing identity safely.")
        process_runner.run(
            (
                keytool,
                "-importkeystore",
                "-noprompt",
                "-srckeystore",
                legacy_key,
                "-srcstorepass",
                password,
                "-srckeypass",
                password,
                "-srcalias",
                alias,
                "-destkeystore",
                staged_key,
                "-deststoretype",
                "PKCS12",
                "-deststorepass",
                password,
                "-destkeypass",
                password,
                "-destalias",
                alias,
            ),
            token=cancellation,
            log=log,
            secret_values={password},
        )
        staged_metadata.write_text(
            json.dumps({"alias": alias, "password": password}, indent=2) + "\n",
            encoding="utf-8",
        )
        process_runner.run(
            (
                keytool,
                "-list",
                "-keystore",
                staged_key,
                "-storetype",
                "PKCS12",
                "-storepass",
                password,
                "-alias",
                alias,
            ),
            token=cancellation,
            log=log,
            secret_values={password},
        )
        if os.name != "nt":
            mode = stat.S_IRUSR | stat.S_IWUSR
            staged_key.chmod(mode)
            staged_metadata.chmod(mode)
        cancellation.raise_if_cancelled()
        # Move the two identity files into place individually: the signing folder may
        # already hold auxiliary entries (app icons, imported identities, .DS_Store)
        # that must survive, so the folder itself is never replaced.
        signing_root.mkdir(parents=True, exist_ok=True)
        os.replace(staged_key, destination_key)
        os.replace(staged_metadata, destination_metadata)
        shutil.rmtree(staging, ignore_errors=True)
        activated = True
        if log:
            log("Existing signing identity migrated; the original legacy files were preserved.")
        return True
    except (OSError, CommandFailed, json.JSONDecodeError) as exc:
        raise LegacyIdentityMigrationError(
            f"The existing signing identity could not be migrated safely: {exc}"
        ) from exc
    finally:
        if not activated:
            shutil.rmtree(staging, ignore_errors=True)
