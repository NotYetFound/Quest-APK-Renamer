import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from quest_renamer.domain.library import GameProfile
from quest_renamer.infrastructure.library_archive import (
    LibraryArchiveError,
    export_library_archive,
    import_library_archive,
    inspect_library_archive,
)


class LibraryArchiveTests(unittest.TestCase):
    def _profile(self, root: Path, name: str, suffix: str) -> GameProfile:
        key = root / f"{suffix}.p12"
        metadata = root / f"{suffix}.json"
        icon = root / f"{suffix}.png"
        key.write_bytes(f"private key {suffix}".encode())
        metadata.write_text(
            json.dumps({"alias": f"alias-{suffix}", "password": f"password-{suffix}"}),
            encoding="utf-8",
        )
        icon.write_bytes(b"\x89PNG\r\n\x1a\n" + suffix.encode())
        return GameProfile.create(
            game_name=name,
            original_package=f"com.example.{suffix}",
            target_package=f"com.dev.example.{suffix}",
            signing_keystore=str(key),
            signing_metadata=str(metadata),
            app_icon=str(icon),
            source_path=str(root / "source" / suffix),
            output_path=str(root / "output" / suffix),
        )

    def test_single_identity_round_trip_includes_key_metadata_and_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "Example Game", "game")
            archive = export_library_archive(root / "one", (profile,))

            summary = inspect_library_archive(archive)
            imported = import_library_archive(archive, root / "new-signing")

            self.assertEqual(archive.suffix, ".qarlib")
            self.assertEqual(summary.count, 1)
            self.assertEqual(summary.complete_keys, 1)
            self.assertEqual(imported[0].id, profile.id)
            self.assertEqual(imported[0].source_path, profile.source_path)
            self.assertNotEqual(imported[0].signing_keystore, profile.signing_keystore)
            self.assertEqual(
                Path(imported[0].signing_keystore).read_bytes(),
                Path(profile.signing_keystore).read_bytes(),
            )
            self.assertTrue(Path(imported[0].signing_metadata).is_file())
            self.assertTrue(Path(imported[0].app_icon).is_file())
            self.assertTrue(imported[0].key_available)

    def test_full_list_summary_reports_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._profile(root, "First", "first")
            second = self._profile(root, "Second", "second")
            archive = export_library_archive(root / "all.qarlib", (first, second))

            summary = inspect_library_archive(archive, {second.id})

            self.assertEqual(summary.count, 2)
            self.assertEqual(summary.names, ("First", "Second"))
            self.assertEqual(summary.replacements, 1)
            self.assertEqual(summary.complete_keys, 2)

    def test_tampered_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "Example", "game")
            original = export_library_archive(root / "original.qarlib", (profile,))
            tampered = root / "tampered.qarlib"
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    data = source.read(info)
                    if info.filename.endswith("signing-key.p12"):
                        data += b"tampered"
                    target.writestr(info.filename, data)

            with self.assertRaisesRegex(LibraryArchiveError, "size is invalid"):
                inspect_library_archive(tampered)

    def test_archive_with_mismatched_profile_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "Example", "game")
            original = export_library_archive(root / "original.qarlib", (profile,))
            invalid = root / "invalid.qarlib"
            with zipfile.ZipFile(original) as source:
                payload = json.loads(source.read("library.json"))
                payload["identities"][0]["profile"]["id"] = "0" * 20
                entries = {
                    info.filename: source.read(info)
                    for info in source.infolist()
                    if info.filename != "library.json"
                }
            with zipfile.ZipFile(invalid, "w") as target:
                target.writestr("library.json", json.dumps(payload))
                for name, data in entries.items():
                    target.writestr(name, data)

            with self.assertRaisesRegex(LibraryArchiveError, "invalid identity"):
                inspect_library_archive(invalid)


if __name__ == "__main__":
    unittest.main()
