import unittest

from quest_renamer.domain.bulk import package_with_suffix


class BulkRulesTests(unittest.TestCase):
    def test_suffix_is_appended_to_each_package(self) -> None:
        self.assertEqual(
            package_with_suffix("com.example.game", "a"),
            "com.example.gamea",
        )

    def test_suffix_must_be_short_and_package_safe(self) -> None:
        for suffix in ("", ".dev", "bad suffix", "-test", "x" * 25):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                package_with_suffix("com.example.game", suffix)


if __name__ == "__main__":
    unittest.main()
