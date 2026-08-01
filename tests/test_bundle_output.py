import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.models import BuildRequest, BundleDraft
from quest_renamer.infrastructure.bundle_output import obb_destination, write_release_manifest


class BundleOutputTests(unittest.TestCase):
    def test_obb_name_uses_new_package_and_detected_version(self) -> None:
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
            Path("/finished/com.dev.example.game/main.43.com.dev.example.game.obb"),
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
