"""Small GitHub release client for the application's published release channel."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from quest_renamer.domain.releases import (
    ReleaseCheckResult,
    parse_release_version,
    select_latest_release,
)

if TYPE_CHECKING:
    from urllib.request import Request


class ReleaseResponse(Protocol):
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes: ...
    def close(self) -> None: ...


ReleaseOpener = Callable[["Request", float], ReleaseResponse]


@dataclass(frozen=True, slots=True)
class UpdateChannel:
    releases_api: str
    tags_api: str
    releases_page: str
    tag_prefix: str


def _default_open(request: Request, timeout: float) -> ReleaseResponse:
    # urllib/ssl are only needed when a check actually runs (≥1 s after startup).
    from quest_renamer.infrastructure.trusted_https import trusted_urlopen

    return cast(ReleaseResponse, trusted_urlopen(request, timeout))


def load_update_channel(path: Path) -> UpdateChannel:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Update-channel configuration must be an object.")
    try:
        return UpdateChannel(
            releases_api=str(raw["releases_api"]),
            tags_api=str(raw["tags_api"]),
            releases_page=str(raw["releases_page"]),
            tag_prefix=str(raw["tag_prefix"]),
        )
    except KeyError as exc:
        raise ValueError("Update-channel configuration is incomplete.") from exc


class GitHubReleaseChecker:
    def __init__(
        self,
        channel: UpdateChannel,
        *,
        app_version: str,
        opener: ReleaseOpener | None = None,
        timeout: float = 8.0,
    ) -> None:
        self._channel = channel
        self._app_version = app_version
        self._opener = opener or _default_open
        self._timeout = timeout

    def _fetch_json(self, url: str) -> object:
        from urllib.request import Request

        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"Quest-APK-Renamer/{self._app_version}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with closing(self._opener(request, self._timeout)) as response:
            return json.loads(response.read().decode("utf-8"))

    def check(self) -> ReleaseCheckResult:
        current = parse_release_version(self._app_version)
        if current is None:
            raise ValueError(f"The app version is invalid: {self._app_version}")
        try:
            releases = self._fetch_json(self._channel.releases_api)
            latest = select_latest_release(
                releases,
                tag_prefix=self._channel.tag_prefix,
            )
        except (OSError, json.JSONDecodeError, ValueError) as release_error:
            try:
                tags = self._fetch_json(self._channel.tags_api)
                if not isinstance(tags, list):
                    raise ValueError("GitHub returned an unexpected tag response.")
                tag_payloads = [
                    {
                        "tag_name": str(raw.get("name") or ""),
                        "name": str(raw.get("name") or ""),
                        "html_url": self._channel.releases_page,
                        "prerelease": "-" in str(raw.get("name") or ""),
                    }
                    for raw in tags
                    if isinstance(raw, dict)
                ]
                latest = select_latest_release(
                    tag_payloads,
                    tag_prefix=self._channel.tag_prefix,
                )
            except (OSError, json.JSONDecodeError, ValueError) as tag_error:
                raise OSError(
                    f"GitHub release and tag checks failed: {release_error}; {tag_error}"
                ) from tag_error
        return ReleaseCheckResult(current=current, latest=latest)
