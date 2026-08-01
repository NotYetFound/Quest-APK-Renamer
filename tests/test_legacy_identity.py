import json
import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.legacy_identity import (
    LEGACY_KEYSTORE_NAME,
    LEGACY_METADATA_NAME,
    LegacyIdentityMigrationError,
    migrate_legacy_signing_identity,
)


class MigrationRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[object, ...], **_kwargs: object) -> None:
        normalized = tuple(str(value) for value in command)
        self.commands.append(normalized)
        if "-importkeystore" in normalized:
            destination = Path(normalized[normalized.index("-destkeystore") + 1])
            destination.write_bytes(b"converted-pkcs12")


class LegacyIdentityMigrationTests(unittest.TestCase):
    def test_migrates_complete_legacy_pair_without_altering_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_data = Path(temporary)
            legacy_key = app_data / LEGACY_KEYSTORE_NAME
            legacy_metadata = app_data / LEGACY_METADATA_NAME
            legacy_key.write_bytes(b"legacy-key")
            legacy_metadata.write_text(
                json.dumps({"alias": "quest-renamer", "password": "private"}),
                encoding="utf-8",
            )
            keytool = app_data / "keytool"
            keytool.touch()
            runner = MigrationRunner()

            migrated = migrate_legacy_signing_identity(
                app_data,
                app_data / "signing",
                keytool,
                runner=runner,  # type: ignore[arg-type]
                token=CancellationToken(),
            )

            self.assertTrue(migrated)
            self.assertEqual(
                (app_data / "signing" / "quest-renamer.p12").read_bytes(),
                b"converted-pkcs12",
            )
            self.assertEqual(legacy_key.read_bytes(), b"legacy-key")
            self.assertTrue(legacy_metadata.is_file())
            self.assertIn("-importkeystore", runner.commands[0])
            self.assertIn("-list", runner.commands[1])

    def test_incomplete_legacy_pair_is_never_replaced_with_a_new_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_data = Path(temporary)
            (app_data / LEGACY_KEYSTORE_NAME).write_bytes(b"legacy-key")
            keytool = app_data / "keytool"
            keytool.touch()

            with self.assertRaises(LegacyIdentityMigrationError):
                migrate_legacy_signing_identity(app_data, app_data / "signing", keytool)

            self.assertTrue((app_data / LEGACY_KEYSTORE_NAME).is_file())
            self.assertFalse((app_data / "signing").exists())

    def test_existing_new_identity_wins_over_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_data = Path(temporary)
            signing = app_data / "signing"
            signing.mkdir()
            (signing / "quest-renamer.p12").write_bytes(b"new")
            (signing / "identity.json").write_text("{}", encoding="utf-8")
            (app_data / LEGACY_KEYSTORE_NAME).write_bytes(b"legacy")
            (app_data / LEGACY_METADATA_NAME).write_text("{}", encoding="utf-8")

            self.assertFalse(migrate_legacy_signing_identity(app_data, signing, None))
            self.assertEqual((signing / "quest-renamer.p12").read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
