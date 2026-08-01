"""Release versions and update-selection rules without network or UI dependencies."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_PATTERN = re.compile(
    r"(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?"
    r"(?:[-.]?(?P<label>alpha|a|beta|b|rc|preview)[.-]?(?P<number>\d+)?)?",
    re.IGNORECASE,
)
_PREVIEW_ORDER = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "preview": 1, "rc": 2}
_LEGACY_RELEASE_VERSIONS = {
    (1, 8, 0): (1, 1, 0),
    (1, 9, 0): (1, 2, 0),
}


@dataclass(frozen=True, order=True, slots=True)
class ReleaseVersion:
    major: int
    minor: int
    patch: int
    stability: int = 3
    preview_number: int = 0


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    tag: str
    name: str
    url: str
    version: ReleaseVersion
    prerelease: bool = False


@dataclass(frozen=True, slots=True)
class ReleaseCheckResult:
    current: ReleaseVersion
    latest: ReleaseInfo | None = None

    @property
    def has_update(self) -> bool:
        return self.latest is not None and self.latest.version > self.current


def parse_release_version(value: str, *, prefix: str = "") -> ReleaseVersion | None:
    cleaned = value.strip()
    if prefix:
        if not cleaned.lower().startswith(prefix.lower()):
            return None
        cleaned = cleaned[len(prefix) :]
    else:
        cleaned = cleaned.lstrip("vV")
    match = _VERSION_PATTERN.fullmatch(cleaned)
    if match is None:
        return None
    label = (match.group("label") or "").lower()
    stability = _PREVIEW_ORDER.get(label, 3)
    numeric = (
        int(match.group("major")),
        int(match.group("minor") or 0),
        int(match.group("patch") or 0),
    )
    major, minor, patch = _LEGACY_RELEASE_VERSIONS.get(numeric, numeric)
    return ReleaseVersion(
        major,
        minor,
        patch,
        stability,
        int(match.group("number") or 0),
    )


def select_latest_release(
    payloads: object,
    *,
    tag_prefix: str,
) -> ReleaseInfo | None:
    if not isinstance(payloads, list):
        raise ValueError("GitHub returned an unexpected release response.")
    releases: list[ReleaseInfo] = []
    for raw in payloads:
        if not isinstance(raw, dict) or raw.get("draft"):
            continue
        tag = str(raw.get("tag_name") or raw.get("name") or "")
        version = parse_release_version(tag, prefix=tag_prefix)
        if version is None:
            continue
        releases.append(
            ReleaseInfo(
                tag=tag,
                name=str(raw.get("name") or tag),
                url=str(raw.get("html_url") or ""),
                version=version,
                prerelease=bool(raw.get("prerelease")),
            )
        )
    return max(releases, key=lambda item: item.version) if releases else None
