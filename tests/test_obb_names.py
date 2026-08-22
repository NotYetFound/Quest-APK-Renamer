import unittest
from pathlib import Path

from quest_renamer.domain.obb_names import (
    ObbNameError,
    parse_obb_filename,
    renamed_obb_filenames,
)


class ObbNameTests(unittest.TestCase):
    def test_parser_accepts_numeric_and_unreal_chunk_tags(self) -> None:
        numeric = parse_obb_filename("main.5513.com.Sanzaru.Wrath2.obb")
        chunk = parse_obb_filename(
            "patch.pakchunk27_s1optional-Android_ASTC.com.Sanzaru.Wrath2.obb"
        )

        self.assertIsNotNone(numeric)
        self.assertIsNotNone(chunk)
        self.assertEqual(numeric.tag, "5513")  # type: ignore[union-attr]
        self.assertEqual(  # type: ignore[union-attr]
            chunk.tag,
            "pakchunk27_s1optional-Android_ASTC",
        )
        self.assertEqual(chunk.package_name, "com.Sanzaru.Wrath2")  # type: ignore[union-attr]

    def test_parser_rejects_paths_spaces_and_invalid_packages(self) -> None:
        for name in (
            "patch.bad tag.com.example.game.obb",
            "patch.tag.com.2example.game.obb",
            "assets.obb",
            "patch.tag.obb",
        ):
            with self.subTest(name=name):
                self.assertIsNone(parse_obb_filename(name))

    def test_collision_check_is_case_insensitive(self) -> None:
        sources = (
            Path("/one/main.42.com.example.game.obb"),
            Path("/two/MAIN.42.com.example.game.OBB"),
        )

        with self.assertRaisesRegex(ObbNameError, "overwrite the same output"):
            renamed_obb_filenames(
                sources,
                source_package="com.example.game",
                target_package="com.dev.example.game",
            )

    def test_safe_package_folder_asset_name_is_preserved(self) -> None:
        self.assertEqual(
            renamed_obb_filenames(
                (Path("/bundle/assets_0.obb"),),
                source_package="com.example.game",
                target_package="com.dev.example.game",
            ),
            ("assets_0.obb",),
        )


if __name__ == "__main__":
    unittest.main()
