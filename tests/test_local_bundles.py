import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.local_bundles import (
    BundleSelectionError,
    LocalBundleInspector,
)


class LocalBundleTests(unittest.TestCase):
    def test_folder_bundle_is_discovered_without_modifying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            obb_dir = root / "com.studio.game"
            obb_dir.mkdir()
            obb = obb_dir / "main.42.com.studio.game.obb"
            obb.write_bytes(b"obb")
            manifest = root / "release.manifest"
            manifest.write_text(
                "#VRPRELEASEMANIFEST 1.0\n"
                "Game Name;Release Name;Package Name;Version Code;Last Updated;"
                "Size (MB);Downloads;Rating;Rating Count\n"
                "Example Game;Example;com.studio.game;42;;;0;0;0\n",
                encoding="utf-8",
            )

            bundle = LocalBundleInspector().inspect_folder(root)

            self.assertEqual(bundle.apk, apk.resolve())
            self.assertEqual(bundle.obbs, (obb.resolve(),))
            self.assertEqual(bundle.package_name, "com.studio.game")
            self.assertEqual(bundle.version_code, "42")
            self.assertEqual(bundle.game_name, "Example Game")

    def test_ambiguous_folder_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.apk").touch()
            (root / "two.apk").touch()

            with self.assertRaisesRegex(BundleSelectionError, "multiple APKs"):
                LocalBundleInspector().inspect_folder(root)

    def test_exact_apk_selection_works_in_a_folder_with_multiple_apks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "selected.apk"
            selected.write_bytes(b"selected")
            (root / "other.apk").write_bytes(b"other")

            bundle = LocalBundleInspector().inspect_apk(selected)

            self.assertEqual(bundle.apk, selected.resolve())

    def test_exact_apk_in_mixed_folder_does_not_claim_neighboring_obbs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "selected.apk"
            selected.write_bytes(b"selected")
            (root / "other.apk").write_bytes(b"other")
            obb_dir = root / "com.other.game"
            obb_dir.mkdir()
            (obb_dir / "main.5.com.other.game.obb").write_bytes(b"other")

            bundle = LocalBundleInspector().inspect_apk(selected)

            self.assertEqual(bundle.obbs, ())

    def test_analyzed_apk_claims_only_matching_obbs_from_a_mixed_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "selected.apk"
            selected.write_bytes(b"selected")
            (root / "other.apk").write_bytes(b"other")
            wanted = root / "com.example.game"
            unrelated = root / "com.other.game"
            wanted.mkdir()
            unrelated.mkdir()
            expected = wanted / "patch.pakchunk0-Android_ASTC.com.example.game.obb"
            expected.write_bytes(b"wanted")
            (unrelated / "main.5.com.other.game.obb").write_bytes(b"other")

            inspector = LocalBundleInspector()
            initial = inspector.inspect_apk(selected)
            analyzed = inspector.apply_apk_identity(initial, "com.example.game")

            self.assertEqual(initial.obbs, ())
            self.assertEqual(analyzed.obbs, (expected.resolve(),))
            self.assertEqual(analyzed.package_name, "com.example.game")

    def test_analyzed_package_folder_rejects_mismatched_obb_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "game.apk"
            selected.write_bytes(b"selected")
            expected = root / "com.example.game"
            expected.mkdir()
            (expected / "main.5.com.other.game.obb").write_bytes(b"other")

            inspector = LocalBundleInspector()
            initial = inspector.inspect_apk(selected)

            with self.assertRaisesRegex(BundleSelectionError, "mismatched"):
                inspector.apply_apk_identity(initial, "com.example.game")

    def test_empty_manifest_package_folder_does_not_trigger_broad_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            (root / "com.example.game").mkdir()
            unrelated = root / "com.other.game"
            unrelated.mkdir()
            (unrelated / "main.5.com.other.game.obb").write_bytes(b"other")
            (root / "release.manifest").write_text(
                "Game Name;Package Name;Version Code\n"
                "Example;com.example.game;42\n",
                encoding="utf-8",
            )

            bundle = LocalBundleInspector().inspect_folder(root)

            self.assertEqual(bundle.obbs, ())

    def test_folder_with_multiple_obb_packages_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "game.apk").write_bytes(b"apk")
            for package in ("com.example.one", "com.example.two"):
                directory = root / package
                directory.mkdir()
                (directory / f"main.1.{package}.obb").write_bytes(package.encode())

            with self.assertRaisesRegex(BundleSelectionError, "multiple packages"):
                LocalBundleInspector().inspect_folder(root)

    def test_safe_asset_obb_in_selected_game_folder_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "game.apk").write_bytes(b"apk")
            asset = root / "first.obb"
            asset.write_bytes(b"data")

            bundle = LocalBundleInspector().inspect_folder(root)

            self.assertEqual(bundle.obbs, (asset.resolve(),))

    def test_unsafe_asset_obb_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "game.apk").write_bytes(b"apk")
            (root / "bad asset.obb").write_bytes(b"data")

            with self.assertRaisesRegex(BundleSelectionError, "unsupported names"):
                LocalBundleInspector().inspect_folder(root)

    def test_unreal_pakchunk_obb_names_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "game.apk").write_bytes(b"apk")
            package = "com.Sanzaru.Wrath2"
            obb_dir = root / package
            obb_dir.mkdir()
            names = (
                f"main.5513.{package}.obb",
                f"patch.0.{package}.obb",
                f"patch.pakchunk0-Android_ASTC.{package}.obb",
                f"patch.pakchunk27_s1optional-Android_ASTC.{package}.obb",
            )
            for name in names:
                (obb_dir / name).write_bytes(name.encode())
            (root / "release.manifest").write_text(
                "Game Name;Package Name;Version Code\n"
                f"Asgard's Wrath 2;{package};5513\n",
                encoding="utf-8",
            )

            bundle = LocalBundleInspector().inspect_folder(root)

            self.assertEqual([path.name for path in bundle.obbs], sorted(names))


if __name__ == "__main__":
    unittest.main()
