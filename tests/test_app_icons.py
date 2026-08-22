import tempfile
import unittest
import zipfile
from pathlib import Path

from quest_renamer.infrastructure.app_icons import (
    cache_apk_icon,
    cache_decoded_app_icon,
    decoded_app_label,
    display_name_key,
)


class AppIconTests(unittest.TestCase):
    def test_display_name_cache_key_ignores_case_and_repeated_space(self) -> None:
        self.assertEqual(display_name_key("Example Game"), display_name_key(" example  GAME "))
        self.assertNotEqual(display_name_key("Example Game"), display_name_key("Other Game"))

    def test_apps_with_the_same_display_name_reuse_one_cached_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.apk"
            second = root / "second.apk"
            cache = root / "icons"
            first_png = b"\x89PNG\r\n\x1a\nfirst"
            second_png = b"\x89PNG\r\n\x1a\nsecond"
            with zipfile.ZipFile(first, "w") as archive:
                archive.writestr("res/mipmap-xxxhdpi/ic_launcher.png", first_png)
            with zipfile.ZipFile(second, "w") as archive:
                archive.writestr("res/mipmap-xxxhdpi/ic_launcher.png", second_png)

            first_path = cache_apk_icon(first, "Example Game", cache)
            second_path = cache_apk_icon(second, "example  game", cache)

            self.assertIsNotNone(first_path)
            self.assertEqual(second_path, first_path)
            self.assertEqual(first_path.read_bytes(), first_png)  # type: ignore[union-attr]

    def test_adaptive_only_or_unreadable_apk_uses_ui_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            apk.write_bytes(b"not a zip")

            self.assertIsNone(cache_apk_icon(apk, "Example", root / "icons"))

    def test_corrupt_cached_icon_is_replaced_from_the_apk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            cache = root / "icons"
            cache.mkdir()
            cached = cache / f"{display_name_key('Example')}.png"
            cached.write_bytes(b"broken")
            png = b"\x89PNG\r\n\x1a\nreplacement"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("res/mipmap-xxxhdpi/ic_launcher.png", png)

            result = cache_apk_icon(apk, "Example", cache)

            self.assertEqual(result, cached)
            self.assertEqual(cached.read_bytes(), png)

    def test_full_decode_resolves_display_name_and_manifest_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decoded = root / "decoded"
            values = decoded / "res" / "values"
            icons = decoded / "res" / "mipmap-xxxhdpi"
            values.mkdir(parents=True)
            icons.mkdir(parents=True)
            (decoded / "AndroidManifest.xml").write_text(
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                '<application android:label="@string/app_name" '
                'android:icon="@mipmap/ic_launcher" />'
                "</manifest>",
                encoding="utf-8",
            )
            (values / "strings.xml").write_text(
                '<resources><string name="app_name">Visible Quest Name</string></resources>',
                encoding="utf-8",
            )
            png = b"\x89PNG\r\n\x1a\nicon"
            (icons / "ic_launcher.png").write_bytes(png)

            label = decoded_app_label(decoded)
            icon = cache_decoded_app_icon(decoded, label, root / "cache")

            self.assertEqual(label, "Visible Quest Name")
            self.assertIsNotNone(icon)
            self.assertEqual(icon.read_bytes(), png)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
