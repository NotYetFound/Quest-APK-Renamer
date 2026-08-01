import unittest

from quest_renamer.domain.package_ids import (
    is_valid_package_id,
    package_id_error,
    with_tag,
)


class PackageIdTests(unittest.TestCase):
    def test_package_id_validation(self) -> None:
        self.assertTrue(is_valid_package_id("com.studio.game"))
        self.assertTrue(is_valid_package_id("com2.studio_name.game7"))
        self.assertFalse(is_valid_package_id("game"))
        self.assertFalse(is_valid_package_id("com.studio.bad-name"))

    def test_tag_is_inserted_as_separate_segment(self) -> None:
        self.assertEqual(with_tag("com.studio.game", "dev"), "com.dev.studio.game")
        self.assertEqual(with_tag("com.dev.studio.game", "dev"), "com.dev.studio.game")

    def test_package_error_requires_a_separate_identity(self) -> None:
        source = "com.studio.game"
        self.assertTrue(package_id_error(source, source))
        self.assertFalse(package_id_error(source, source, allow_same=True))
        self.assertFalse(package_id_error("com.dev.studio.game", source))


if __name__ == "__main__":
    unittest.main()
