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

            self.assertEqual(bundle.apk, apk)
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


if __name__ == "__main__":
    unittest.main()
