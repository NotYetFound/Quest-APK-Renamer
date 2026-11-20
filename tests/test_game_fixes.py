import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from expansion_fixtures import CancelOnCheck, build_catalog, write_obb

from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure.addressables_catalog import (
    CATALOG_ENTRY,
    resolve_catalog_internal_ids,
)
from quest_renamer.infrastructure.game_fixes import (
    GAME_FIXES,
    DecodedApkFixResult,
    GameFixContext,
    GameFixError,
    fixes_for,
    walkabout_mini_golf,
)
from quest_renamer.infrastructure.game_fixes.walkabout_mini_golf import (
    ObbCatalogRewrite,
    WalkaboutMiniGolfFix,
    rewrite_obb_catalog,
)

OLD = "com.MightyCoconut.WalkaboutMiniGolf"
NEW = "com.mr.MightyCoconut.WalkaboutMiniGolf"
# The target package is whatever the user chose; the fix must not depend on the
# ".mr" prefix or on the new ID being longer than the old one.
OTHER_TARGETS = (
    "com.wmg",  # much shorter than OLD
    "com.dev.MightyCoconut.WalkaboutMiniGolf",  # the app's default prefix
    "org.example.quest.renamed.MightyCoconut.WalkaboutMiniGolf.copy2",  # longer
)
# Expansion-file version tags change with every game update; the fix must not
# depend on any particular one.
TAG = "999999"


def _config(abi: str = "arm64-v8a") -> Path:
    return Path("lib") / abi / "libfrda.config.so"


def _context(token: CancellationToken) -> GameFixContext:
    return GameFixContext(OLD, NEW, token, lambda _line: None)


def patch_obb_expansion_paths(
    obb: Path, old: str, new: str, *, token: CancellationToken
) -> ObbCatalogRewrite | None:
    return rewrite_obb_catalog(obb, GameFixContext(old, new, token, lambda _line: None))


def patch_decoded_expansion_paths(
    decoded: Path, old: str, new: str, *, token: CancellationToken
) -> DecodedApkFixResult:
    context = GameFixContext(old, new, token, lambda _line: None)
    return WalkaboutMiniGolfFix().apply_to_decoded_apk(context, decoded)


class RegistryTests(unittest.TestCase):
    def test_walkabout_source_package_selects_the_walkabout_fix(self) -> None:
        fixes = fixes_for("com.MightyCoconut.WalkaboutMiniGolf")
        self.assertEqual(len(fixes), 1)
        self.assertIsInstance(fixes[0], WalkaboutMiniGolfFix)

    def test_other_packages_select_nothing(self) -> None:
        for package in (
            "com.example.game",
            "com.mightycoconut.walkaboutminigolf",
            "COM.MIGHTYCOCONUT.WALKABOUTMINIGOLF",
            "com.mr.MightyCoconut.WalkaboutMiniGolf",
            "",
        ):
            with self.subTest(package=package):
                self.assertEqual(fixes_for(package), ())

    def test_registered_fixes_are_well_formed(self) -> None:
        self.assertTrue(GAME_FIXES)
        ids = [fix.fix_id for fix in GAME_FIXES]
        self.assertEqual(len(ids), len(set(ids)))
        for fix in GAME_FIXES:
            with self.subTest(fix=fix.fix_id):
                self.assertRegex(fix.fix_id, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertTrue(fix.title)
                self.assertTrue(fix.source_packages)

    def test_no_two_fixes_claim_the_same_source_package(self) -> None:
        claimed: set[str] = set()
        for fix in GAME_FIXES:
            self.assertFalse(claimed & fix.source_packages)
            claimed |= fix.source_packages

    def test_game_fix_error_is_a_value_error(self) -> None:
        self.assertTrue(issubclass(GameFixError, ValueError))

    def test_fix_reports_apk_and_obb_changes(self) -> None:
        fix = WalkaboutMiniGolfFix()
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary) / "decoded"
            config = decoded / _config()
            config.parent.mkdir(parents=True)
            config.write_bytes(f'{{"path":"main.{TAG}.{OLD}.obb"}}'.encode())
            obb = Path(temporary) / "main.555.com.example.game.obb"
            write_obb(obb, build_catalog([[OLD, "content"]]))
            context = _context(CancellationToken())

            result = fix.apply_to_decoded_apk(context, decoded)
            lines = fix.apply_to_obb(context, obb)

            self.assertEqual(result.rewritten_files, ("lib/arm64-v8a/libfrda.config.so",))
            self.assertEqual(len(result.report), 1)
            self.assertEqual(len(lines), 1)
            self.assertIn(CATALOG_ENTRY, lines[0])
            self.assertEqual(fix.apply_to_obb(context, obb), ())


class ObbRewriteTests(unittest.TestCase):
    def _obb(self, temporary: str, *, compressed: bool = False) -> Path:
        path = Path(temporary) / "main.555.com.example.game.obb"
        write_obb(path, build_catalog([[OLD, "content"]]), compressed=compressed)
        return path

    def test_stored_catalog_is_rewritten_and_archive_stays_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = self._obb(temporary)
            original = obb.stat().st_size

            fix = patch_obb_expansion_paths(
                obb, OLD, NEW, token=CancellationToken()
            )

            self.assertIsNotNone(fix)
            assert fix is not None
            self.assertEqual(fix.size_delta, 4 + len(NEW))
            self.assertEqual(obb.stat().st_size, original + fix.size_delta)
            with zipfile.ZipFile(obb) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(
                    archive.namelist(),
                    [
                        "assets/aa/before.bin",
                        CATALOG_ENTRY,
                        "assets/aa/after.bin",
                    ],
                )
                catalog = archive.read(CATALOG_ENTRY)
                self.assertEqual(archive.read("assets/aa/after.bin"), b"after" * 4096)
            internal_ids = resolve_catalog_internal_ids(catalog)
            self.assertFalse(any(OLD in value for value in internal_ids))
            self.assertTrue(any(NEW in value for value in internal_ids))

    def test_any_target_package_is_written_into_the_catalog(self) -> None:
        for new in OTHER_TARGETS:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as temporary:
                obb = Path(temporary) / "main.555.com.example.game.obb"
                write_obb(obb, build_catalog([[OLD, "content"], [OLD, "levels"]]))
                original = obb.stat().st_size

                fix = patch_obb_expansion_paths(
                    obb, OLD, new, token=CancellationToken()
                )

                self.assertIsNotNone(fix)
                assert fix is not None
                self.assertEqual(fix.size_delta, 4 + len(new))
                self.assertEqual(obb.stat().st_size, original + fix.size_delta)
                with zipfile.ZipFile(obb) as archive:
                    self.assertIsNone(archive.testzip())
                    ids = resolve_catalog_internal_ids(archive.read(CATALOG_ENTRY))
                self.assertEqual(ids, (f"{new}/content", f"{new}/levels"))
                self.assertIsNone(
                    patch_obb_expansion_paths(obb, OLD, new, token=CancellationToken())
                )

    def test_second_patch_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = self._obb(temporary)
            patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())
            first = obb.read_bytes()

            second = patch_obb_expansion_paths(
                obb, OLD, NEW, token=CancellationToken()
            )

            self.assertIsNone(second)
            self.assertEqual(obb.read_bytes(), first)

    def test_compressed_catalog_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = self._obb(temporary, compressed=True)
            before = obb.read_bytes()
            with self.assertRaisesRegex(GameFixError, "compressed"):
                patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())
            self.assertEqual(obb.read_bytes(), before)

    def test_data_descriptor_flag_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = self._obb(temporary)
            with zipfile.ZipFile(obb) as archive:
                info = archive.getinfo(CATALOG_ENTRY)
            data = bytearray(obb.read_bytes())
            local_flags = struct.unpack_from("<H", data, info.header_offset + 6)[0]
            struct.pack_into("<H", data, info.header_offset + 6, local_flags | 0x8)
            eocd = data.rfind(b"PK\x05\x06")
            position = struct.unpack_from("<I", data, eocd + 16)[0]
            while position < len(data):
                if struct.unpack_from("<I", data, position)[0] != 0x02014B50:
                    break
                if struct.unpack_from("<I", data, position + 42)[0] == info.header_offset:
                    flags = struct.unpack_from("<H", data, position + 8)[0]
                    struct.pack_into("<H", data, position + 8, flags | 0x8)
                    break
                name_length, extra_length, comment_length = struct.unpack_from(
                    "<HHH", data, position + 28
                )
                position += 46 + name_length + extra_length + comment_length
            obb.write_bytes(data)

            with self.assertRaisesRegex(GameFixError, "data descriptor"):
                patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())

    def test_catalog_as_the_last_entry_is_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = Path(temporary) / "main.42.com.example.game.obb"
            write_obb(
                obb,
                build_catalog([[OLD, "content"]]),
                catalog_last=True,
            )

            fix = patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())

            self.assertIsNotNone(fix)
            with zipfile.ZipFile(obb) as archive:
                self.assertIsNone(archive.testzip())
                ids = resolve_catalog_internal_ids(archive.read(CATALOG_ENTRY))
            self.assertEqual(ids, (f"{NEW}/content",))

    def test_archive_comment_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = Path(temporary) / "main.42.com.example.game.obb"
            write_obb(
                obb,
                build_catalog([[OLD, "content"]]),
                comment=b"OBB comment",
            )

            patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())

            with zipfile.ZipFile(obb) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.comment, b"OBB comment")

    def test_corrupt_central_directory_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = self._obb(temporary)
            data = bytearray(obb.read_bytes())
            eocd = data.rfind(b"PK\x05\x06")
            central = struct.unpack_from("<I", data, eocd + 16)[0]
            data[central : central + 4] = b"XXXX"
            obb.write_bytes(data)

            with self.assertRaisesRegex(GameFixError, "readable OBB"):
                patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())

    def test_zip64_sentinel_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = self._obb(temporary)
            data = bytearray(obb.read_bytes())
            eocd = data.rfind(b"PK\x05\x06")
            struct.pack_into("<I", data, eocd + 16, 0xFFFFFFFF)
            obb.write_bytes(data)

            with self.assertRaises(GameFixError):
                patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())

    def test_refused_catalog_surfaces_as_game_fix_error(self) -> None:
        for label, catalog in (
            ("bad signature", bytes(64)),
            ("longer segment", build_catalog([[f"prefix-{OLD}-suffix", "content"]])),
        ):
            with self.subTest(label), tempfile.TemporaryDirectory() as temporary:
                obb = Path(temporary) / "main.555.com.example.game.obb"
                write_obb(obb, catalog)
                before = obb.read_bytes()
                with self.assertRaises(GameFixError):
                    WalkaboutMiniGolfFix().apply_to_obb(
                        _context(CancellationToken()), obb
                    )
                self.assertEqual(obb.read_bytes(), before)

    def test_cancellation_between_catalog_patch_and_zip_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = self._obb(temporary)
            before = obb.read_bytes()
            # Checks: 1 after reading the catalog, 2 after computing the patch.
            token = CancelOnCheck(2)
            with (
                mock.patch.object(walkabout_mini_golf, "rewrite_stored_entry") as rewrite,
                self.assertRaises(OperationCancelled),
            ):
                rewrite_obb_catalog(obb, _context(token))
            rewrite.assert_not_called()
            self.assertEqual(obb.read_bytes(), before)

    def test_archive_without_catalog_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = Path(temporary) / "main.555.com.example.game.obb"
            with zipfile.ZipFile(obb, "w") as archive:
                archive.writestr("assets/level.bin", b"level")
            self.assertIsNone(
                patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())
            )

    def test_non_zip_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = Path(temporary) / "main.555.com.example.game.obb"
            obb.write_bytes(b"not a zip")
            self.assertIsNone(
                patch_obb_expansion_paths(obb, OLD, NEW, token=CancellationToken())
            )

class DecodedConfigTests(unittest.TestCase):
    def test_single_expansion_path_is_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            config = decoded / _config()
            config.parent.mkdir(parents=True)
            original = (
                f'{{"path":"main.{TAG}.{OLD}.obb","type":"default"}}'
            ).encode()
            config.write_bytes(original)

            fix = patch_decoded_expansion_paths(
                decoded, OLD, NEW, token=CancellationToken()
            )

            self.assertEqual(fix.rewritten_files, ("lib/arm64-v8a/libfrda.config.so",))
            updated = config.read_bytes()
            self.assertEqual(len(updated), len(original) + len(NEW) - len(OLD))
            self.assertNotIn(OLD.encode(), updated)
            self.assertIn(f"main.{TAG}.{NEW}.obb".encode(), updated)

    def test_any_target_package_is_written_into_the_config(self) -> None:
        for new in OTHER_TARGETS:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as temporary:
                decoded = Path(temporary)
                config = decoded / _config()
                config.parent.mkdir(parents=True)
                config.write_bytes(
                    f'{{"path":"main.{TAG}.{OLD}.obb","type":"default"}}'.encode()
                )

                fix = patch_decoded_expansion_paths(
                    decoded, OLD, new, token=CancellationToken()
                )

                self.assertEqual(
                    fix.rewritten_files, ("lib/arm64-v8a/libfrda.config.so",)
                )
                self.assertEqual(
                    config.read_bytes(),
                    f'{{"path":"main.{TAG}.{new}.obb","type":"default"}}'.encode(),
                )

    def test_any_expansion_version_tag_is_rewritten(self) -> None:
        for tag in ("500001", "1002003", "patch-2027"):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temporary:
                decoded = Path(temporary)
                config = decoded / _config("arm64-v8a")
                config.parent.mkdir(parents=True)
                config.write_bytes(
                    f'{{"path":"main.{tag}.{OLD}.obb"}}'.encode()
                )

                patch_decoded_expansion_paths(
                    decoded, OLD, NEW, token=CancellationToken()
                )

                self.assertEqual(
                    config.read_bytes(),
                    f'{{"path":"main.{tag}.{NEW}.obb"}}'.encode(),
                )

    def test_every_abi_is_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            payload = f'{{"path":"main.{TAG}.{OLD}.obb"}}'.encode()
            for abi in ("arm64-v8a", "armeabi-v7a"):
                path = decoded / _config(abi)
                path.parent.mkdir(parents=True)
                path.write_bytes(payload)

            fix = patch_decoded_expansion_paths(
                decoded, OLD, NEW, token=CancellationToken()
            )

            self.assertEqual(
                fix.rewritten_files,
                (
                    "lib/arm64-v8a/libfrda.config.so",
                    "lib/armeabi-v7a/libfrda.config.so",
                ),
            )
            for entry in fix.rewritten_files:
                self.assertIn(NEW.encode(), (decoded / entry).read_bytes())

    def test_multiple_occurrences_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            config = decoded / _config()
            config.parent.mkdir(parents=True)
            config.write_bytes((f'"{OLD}" and main.{TAG}.{OLD}.obb').encode())
            before = config.read_bytes()

            with self.assertRaisesRegex(GameFixError, "exactly one"):
                patch_decoded_expansion_paths(
                    decoded, OLD, NEW, token=CancellationToken()
                )
            self.assertEqual(config.read_bytes(), before)

    def test_native_library_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            config = decoded / _config()
            config.parent.mkdir(parents=True)
            config.write_bytes(b"\x7fELF" + OLD.encode())
            fix = patch_decoded_expansion_paths(
                decoded, OLD, NEW, token=CancellationToken()
            )
            self.assertEqual(fix.rewritten_files, ())
            self.assertIn(OLD.encode(), config.read_bytes())

    def test_package_outside_an_obb_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            config = decoded / _config()
            config.parent.mkdir(parents=True)
            config.write_bytes(f'{{"applicationId":"{OLD}"}}'.encode())
            with self.assertRaisesRegex(GameFixError, "expansion-file path"):
                patch_decoded_expansion_paths(
                    decoded, OLD, NEW, token=CancellationToken()
                )

    def test_absent_package_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            config = decoded / _config()
            config.parent.mkdir(parents=True)
            config.write_bytes(b'{"path":"main.555.com.other.obb"}')
            fix = patch_decoded_expansion_paths(
                decoded, OLD, NEW, token=CancellationToken()
            )
            self.assertEqual(fix.rewritten_files, ())


if __name__ == "__main__":
    unittest.main()
