import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.package_rewriter import replace_package_references


class PackageRewriterTests(unittest.TestCase):
    def test_only_android_technical_files_are_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            decoded = Path(temporary)
            manifest = decoded / "AndroidManifest.xml"
            smali = decoded / "smali" / "com" / "example" / "Main.smali"
            resource = decoded / "res" / "xml" / "provider.xml"
            asset = decoded / "assets" / "config.json"
            for path in (smali, resource, asset):
                path.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text('package="com.example.game"', encoding="utf-8")
            smali.write_text("Lcom/example/game/Main;", encoding="utf-8")
            resource.write_text("com.example.game.provider", encoding="utf-8")
            asset.write_text('"com.example.game"', encoding="utf-8")

            result = replace_package_references(
                decoded,
                "com.example.game",
                "com.dev.example.game",
                token=CancellationToken(),
            )

            self.assertEqual(result.changed_files, 3)
            self.assertIn("com.dev.example.game", manifest.read_text(encoding="utf-8"))
            self.assertIn("com/dev/example/game", smali.read_text(encoding="utf-8"))
            self.assertEqual(asset.read_text(encoding="utf-8"), '"com.example.game"')
            self.assertEqual(result.preserved_files, ("assets/config.json",))


if __name__ == "__main__":
    unittest.main()
