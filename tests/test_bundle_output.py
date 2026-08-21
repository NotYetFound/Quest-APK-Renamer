import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.models import BuildRequest, BundleDraft
from quest_renamer.infrastructure.bundle_output import obb_destination, write_release_manifest


class BundleOutputTests(unittest.TestCase):
    def test_obb_name_rewrites_package_and_preserves_version(self) -> None:
        root = Path("/bundle")
        source = root / "main.42.com.example.game.obb"
        draft = BundleDraft(
            root,
            root / "game.apk",
            (source,),
            package_name="com.example.game",
            version_code="43",
        )
        request = BuildRequest(draft, "com.dev.example.game", Path("/finished"))

        result = obb_destination(source, request, request.output_root)

        # Only the package segment changes; the version the game references is
        # kept exactly as shipped.
        self.assertEqual(
            result,
            Path("/finished/com.dev.example.game/main.42.com.dev.example.game.obb"),
        )

    def test_unreal_pakchunk_obbs_keep_distinct_names(self) -> None:
        # Reproduces the Asgard's Wrath 2 bundle: one numeric main/patch pair
        # plus many Unreal pak-chunk OBBs whose tag is not a number. The old
        # \d+ pattern collapsed every non-numeric file onto a single
        # "main.<version>.<package>.obb" destination, so only one survived.
        root = Path("/bundle/com.Sanzaru.Wrath2")
        sources = [
            root / "main.5513.com.Sanzaru.Wrath2.obb",
            root / "patch.0.com.Sanzaru.Wrath2.obb",
            root / "patch.pakchunk0-Android_ASTC.com.Sanzaru.Wrath2.obb",
            root / "patch.pakchunk36-Android_ASTC.com.Sanzaru.Wrath2.obb",
            root / "patch.pakchunk27_s1optional-Android_ASTC.com.Sanzaru.Wrath2.obb",
        ]
        draft = BundleDraft(
            root,
            root / "com.Sanzaru.Wrath2.apk",
            tuple(sources),
            package_name="com.Sanzaru.Wrath2",
            version_code="5513",
        )
        request = BuildRequest(draft, "com.dev.Sanzaru.Wrath2", Path("/finished"))

        destinations = [
            obb_destination(source, request, request.output_root) for source in sources
        ]

        package_dir = Path("/finished/com.dev.Sanzaru.Wrath2")
        self.assertEqual(
            destinations,
            [
                package_dir / "main.5513.com.dev.Sanzaru.Wrath2.obb",
                package_dir / "patch.0.com.dev.Sanzaru.Wrath2.obb",
                package_dir / "patch.pakchunk0-Android_ASTC.com.dev.Sanzaru.Wrath2.obb",
                package_dir / "patch.pakchunk36-Android_ASTC.com.dev.Sanzaru.Wrath2.obb",
                package_dir
                / "patch.pakchunk27_s1optional-Android_ASTC.com.dev.Sanzaru.Wrath2.obb",
            ],
        )
        # Every source must land on its own destination, otherwise copies
        # overwrite each other and only one file is transferred.
        self.assertEqual(len(set(destinations)), len(destinations))

    def test_files_without_package_name_are_copied_unchanged(self) -> None:
        root = Path("/bundle")
        draft = BundleDraft(
            root,
            root / "game.apk",
            package_name="com.example.game",
            version_code="43",
        )
        request = BuildRequest(draft, "com.dev.example.game", Path("/finished"))

        result = obb_destination(root / "assets.obb", request, request.output_root)

        self.assertEqual(
            result,
            Path("/finished/com.dev.example.game/assets.obb"),
        )

    def test_release_manifest_quotes_game_names_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "com.dev.example.game.apk"
            apk.write_bytes(b"apk")
            draft = BundleDraft(
                root / "source",
                root / "source" / "game.apk",
                game_name="Example; Game",
                package_name="com.example.game",
                version_code="42",
            )
            request = BuildRequest(draft, "com.dev.example.game", root)

            manifest = write_release_manifest(request, root, apk, ())

            text = manifest.read_text(encoding="utf-8-sig")
            self.assertIn('"Example; Game"', text)
            self.assertIn("com.dev.example.game", text)


if __name__ == "__main__":
    unittest.main()
