import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

from quest_renamer.infrastructure.github_releases import (
    GitHubReleaseChecker,
    UpdateChannel,
    _default_open,
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
        self.assertIn(
            "/repos/NotYetFound/Quest-APK-Renamer/",
            channel.releases_api,
        )
        self.assertEqual(
            channel.releases_page,
            "https://github.com/NotYetFound/Quest-APK-Renamer/releases",
        )

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

    def test_default_opener_uses_a_populated_certificate_context(self) -> None:
        response = FakeResponse(b"[]")
        with patch(
            "quest_renamer.infrastructure.trusted_https.urlopen",
            return_value=response,
        ) as opened:
            returned = _default_open(Request(self.channel.releases_api), 4.0)

        self.assertIs(returned, response)
        self.assertEqual(opened.call_args.kwargs["timeout"], 4.0)
        context = opened.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertGreater(len(context.get_ca_certs()), 0)

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
