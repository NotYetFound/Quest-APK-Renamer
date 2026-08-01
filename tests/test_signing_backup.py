import json
import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.signing import SigningIdentityAlreadyExists
from quest_renamer.infrastructure.signing_backup import SigningIdentityManager


class SigningBackupTests(unittest.TestCase):
    def _identity(self, root: Path, value: bytes = b"key") -> None:
        root.mkdir(parents=True)
        (root / "quest-renamer.p12").write_bytes(value)
        (root / "identity.json").write_text(
            json.dumps({"alias": "quest-renamer", "password": "secret"}),
            encoding="utf-8",
        )

    def test_backup_is_complete_and_marks_the_current_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signing = root / "data" / "signing"
            destination = root / "backups"
            destination.mkdir()
            self._identity(signing)
            manager = SigningIdentityManager(signing)

            result = manager.backup_to(destination)

            self.assertTrue((result.destination / "quest-renamer.p12").is_file())
            self.assertTrue((result.destination / "identity.json").is_file())
            self.assertTrue((result.destination / "backup.json").is_file())
            self.assertTrue(manager.state().backed_up)

    def test_restore_requires_confirmation_and_preserves_the_previous_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signing = root / "data" / "signing"
            restored_identity = root / "restored-identity"
            backup_parent = root / "backups"
            backup_parent.mkdir()
            self._identity(signing, b"current")
            self._identity(restored_identity, b"restored")
            backup = (
                SigningIdentityManager(restored_identity).backup_to(backup_parent).destination
            )
            manager = SigningIdentityManager(signing)

            with self.assertRaises(SigningIdentityAlreadyExists):
                manager.restore_from(backup)
            result = manager.restore_from(backup, replace_existing=True)

            self.assertEqual((signing / "quest-renamer.p12").read_bytes(), b"restored")
            self.assertIsNotNone(result.recovery)
            assert result.recovery is not None
            self.assertEqual(
                (result.recovery / "quest-renamer.p12").read_bytes(),
                b"current",
            )
            self.assertTrue(manager.state().backed_up)

    def test_restore_rejects_a_modified_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signing = root / "identity"
            backup_parent = root / "backups"
            backup_parent.mkdir()
            self._identity(signing)
            backup = SigningIdentityManager(signing).backup_to(backup_parent).destination
            (backup / "quest-renamer.p12").write_bytes(b"changed")

            with self.assertRaisesRegex(RuntimeError, "integrity check"):
                SigningIdentityManager(root / "target").restore_from(backup)

    def test_backup_and_restore_include_lineage_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signing = root / "identity"
            backup_parent = root / "backups"
            backup_parent.mkdir()
            self._identity(signing)
            lineage = signing / "lineage-keys"
            lineage.mkdir()
            (lineage / "signing-abc.p12").write_bytes(b"lineage-key")
            (lineage / "signing-abc.json").write_text(
                json.dumps({"alias": "quest-renamer", "password": "lineage-secret"}),
                encoding="utf-8",
            )
            manager = SigningIdentityManager(signing)

            backup = manager.backup_to(backup_parent).destination
            restored = root / "restored"
            SigningIdentityManager(restored).restore_from(backup)

            self.assertEqual(
                (restored / "lineage-keys" / "signing-abc.p12").read_bytes(),
                b"lineage-key",
            )

    def test_new_lineage_key_marks_an_older_backup_as_outdated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signing = root / "identity"
            backup_parent = root / "backups"
            backup_parent.mkdir()
            self._identity(signing)
            manager = SigningIdentityManager(signing)
            manager.backup_to(backup_parent)
            self.assertTrue(manager.state().backed_up)

            lineage = signing / "lineage-keys"
            lineage.mkdir()
            (lineage / "signing-new.p12").write_bytes(b"new-lineage")

            self.assertFalse(manager.state().backed_up)


if __name__ == "__main__":
    unittest.main()
