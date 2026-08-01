import unittest

from quest_renamer.domain.releases import (
    ReleaseVersion,
    parse_release_version,
    select_latest_release,
)


class ReleaseTests(unittest.TestCase):
    def test_semantic_preview_order(self) -> None:
        beta = parse_release_version("v1.4.0-beta.2", prefix="v")
        release_candidate = parse_release_version("v1.4.0-rc.1", prefix="v")
        stable = parse_release_version("v1.4.0", prefix="v")
        self.assertIsNotNone(beta)
        self.assertIsNotNone(release_candidate)
        self.assertIsNotNone(stable)
        assert beta is not None and release_candidate is not None and stable is not None
        self.assertLess(beta, release_candidate)
        self.assertLess(release_candidate, stable)

    def test_plain_current_version_parses_without_channel_prefix(self) -> None:
        self.assertEqual(parse_release_version("v1.4.0"), ReleaseVersion(1, 4, 0))

    def test_legacy_out_of_sequence_tags_keep_their_published_order(self) -> None:
        self.assertEqual(parse_release_version("v1.8.0"), ReleaseVersion(1, 1, 0))
        self.assertEqual(parse_release_version("v1.9.0"), ReleaseVersion(1, 2, 0))

    def test_selection_uses_full_release_channel_and_ignores_drafts(self) -> None:
        result = select_latest_release(
            [
                {"tag_name": "v1.3.2-beta.1", "html_url": "https://old.invalid"},
                {
                    "tag_name": "v1.5.0-beta.1",
                    "html_url": "https://preview.invalid",
                    "prerelease": True,
                },
                {
                    "tag_name": "v1.6.0",
                    "html_url": "https://draft.invalid",
                    "draft": True,
                },
            ],
            tag_prefix="v",
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tag, "v1.5.0-beta.1")
        self.assertTrue(result.prerelease)


if __name__ == "__main__":
    unittest.main()
