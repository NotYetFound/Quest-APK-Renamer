import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from urllib.error import URLError
from urllib.request import Request

from quest_renamer.infrastructure.github_releases import (
    GitHubReleaseChecker,
    UpdateChannel,
    load_update_channel,
)


class FakeResponse(io.BytesIO):
    headers: ClassVar[dict[str, str]] = {}


class GitHubReleaseCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.channel = UpdateChannel(
            releases_api="https://api.example.invalid/releases",
            tags_api="https://api.example.invalid/tags",
            releases_page="https://example.invalid/releases",
            tag_prefix="v",
        )

    def test_checked_in_channel_is_complete(self) -> None:
        root = Path(__file__).parents[1] / "src" / "quest_renamer"
        channel = load_update_channel(root / "resources" / "update-channel.json")
        self.assertEqual(channel.tag_prefix, "v")
        self.assertTrue(channel.releases_api.startswith("https://api.github.com/"))

    def test_release_check_includes_preview_on_the_full_channel(self) -> None:
        payload = [
            {"tag_name": "v1.3.2-beta.1", "html_url": "https://old.invalid"},
            {
                "tag_name": "v1.5.0-beta.1",
                "name": "1.5 preview",
                "html_url": "https://example.invalid/preview",
                "prerelease": True,
            },
        ]

        def opener(request: Request, timeout: float) -> FakeResponse:
            self.assertEqual(request.full_url, self.channel.releases_api)
            self.assertEqual(timeout, 8.0)
            return FakeResponse(json.dumps(payload).encode())

        result = GitHubReleaseChecker(
            self.channel,
            app_version="1.4.0",
            opener=opener,
        ).check()

        self.assertTrue(result.has_update)
        self.assertEqual(result.latest.tag if result.latest else "", "v1.5.0-beta.1")

    def test_tag_api_is_used_when_release_api_fails(self) -> None:
        calls: list[str] = []

        def opener(request: Request, _timeout: float) -> FakeResponse:
            calls.append(request.full_url)
            if request.full_url == self.channel.releases_api:
                raise URLError("offline")
            return FakeResponse(json.dumps([{"name": "v1.5.0"}]).encode())

        result = GitHubReleaseChecker(
            self.channel,
            app_version="1.4.0",
            opener=opener,
        ).check()

        self.assertTrue(result.has_update)
        self.assertEqual(calls, [self.channel.releases_api, self.channel.tags_api])

    def test_channel_loader_rejects_incomplete_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "channel.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_update_channel(path)


if __name__ == "__main__":
    unittest.main()
