import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.models import BuildRequest, BundleDraft
from quest_renamer.infrastructure.bundle_output import (
    obb_destination,
    obb_destinations,
    write_release_manifest,
)


class BundleOutputTests(unittest.TestCase):
    def test_obb_name_rewrites_package_and_preserves_original_tag(self) -> None:
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

        self.assertEqual(
            result,
            Path("/finished/com.dev.example.game/main.42.com.dev.example.game.obb"),
        )

    def test_unreal_pakchunk_names_stay_distinct_and_keep_their_tags(self) -> None:
        root = Path("/bundle")
        sources = (
            root / "main.5513.com.Sanzaru.Wrath2.obb",
            root / "patch.0.com.Sanzaru.Wrath2.obb",
            root / "patch.pakchunk0-Android_ASTC.com.Sanzaru.Wrath2.obb",
            root / "patch.pakchunk36-Android_ASTC.com.Sanzaru.Wrath2.obb",
            root / "patch.pakchunk27_s1optional-Android_ASTC.com.Sanzaru.Wrath2.obb",
        )
        request = BuildRequest(
            BundleDraft(
                root,
                root / "game.apk",
                sources,
                package_name="com.Sanzaru.Wrath2",
                version_code="5513",
            ),
            "com.dev.Sanzaru.Wrath2",
            Path("/finished"),
        )

        destinations = obb_destinations(request, request.output_root)

        self.assertEqual(
            [path.name for path in destinations],
            [
                "main.5513.com.dev.Sanzaru.Wrath2.obb",
                "patch.0.com.dev.Sanzaru.Wrath2.obb",
                "patch.pakchunk0-Android_ASTC.com.dev.Sanzaru.Wrath2.obb",
                "patch.pakchunk36-Android_ASTC.com.dev.Sanzaru.Wrath2.obb",
                "patch.pakchunk27_s1optional-Android_ASTC.com.dev.Sanzaru.Wrath2.obb",
            ],
        )
        self.assertEqual(len(set(destinations)), len(sources))

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

    def test_safe_asset_obb_name_is_preserved_without_coercion(self) -> None:
        root = Path("/bundle")
        source = root / "data.obb"
        request = BuildRequest(
            BundleDraft(root, root / "game.apk", (source,), package_name="com.example.game"),
            "com.dev.example.game",
            Path("/finished"),
        )

        self.assertEqual(
            obb_destination(source, request, request.output_root),
            Path("/finished/com.dev.example.game/data.obb"),
        )

    def test_unsafe_asset_obb_name_is_rejected(self) -> None:
        root = Path("/bundle")
        source = root / "bad asset.obb"
        request = BuildRequest(
            BundleDraft(root, root / "game.apk", (source,), package_name="com.example.game"),
            "com.dev.example.game",
            Path("/finished"),
        )

        with self.assertRaisesRegex(ValueError, "Unsupported OBB filename"):
            obb_destination(source, request, request.output_root)

    def test_duplicate_computed_obb_destinations_are_rejected(self) -> None:
        root = Path("/bundle")
        first_root = root / "first"
        second_root = root / "second"
        first = first_root / "main.42.com.example.game.obb"
        second = second_root / "main.42.com.example.game.obb"
        request = BuildRequest(
            BundleDraft(
                root,
                root / "game.apk",
                (first, second),
                package_name="com.example.game",
                version_code="42",
            ),
            "com.dev.example.game",
            Path("/finished"),
        )

        with self.assertRaisesRegex(ValueError, "overwrite the same output"):
            obb_destinations(request, request.output_root)

    def test_obb_from_another_package_is_rejected(self) -> None:
        root = Path("/bundle")
        source = root / "patch.pakchunk0-Android_ASTC.com.other.game.obb"
        request = BuildRequest(
            BundleDraft(
                root,
                root / "game.apk",
                (source,),
                package_name="com.example.game",
            ),
            "com.dev.example.game",
            Path("/finished"),
        )

        with self.assertRaisesRegex(ValueError, "belongs to com.other.game"):
            obb_destination(source, request, request.output_root)


if __name__ == "__main__":
    unittest.main()
