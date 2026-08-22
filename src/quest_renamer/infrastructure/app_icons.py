"""Small, best-effort launcher-icon cache for Library rows."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

_IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
_ICON_NAMES = {
    "ic_launcher": 50,
    "ic_launcher_round": 45,
    "app_icon": 40,
    "icon": 35,
    "ic_launcher_foreground": 20,
}
_DENSITY_SCORES = {
    "xxxhdpi": 6,
    "xxhdpi": 5,
    "xhdpi": 4,
    "hdpi": 3,
    "mdpi": 2,
    "ldpi": 1,
}
_ANDROID = "{http://schemas.android.com/apk/res/android}"


def display_name_key(display_name: str) -> str:
    """Return a stable cache key shared by equal human-facing app names."""
    normalized = " ".join(display_name.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _image_kind(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return ""


def _existing_icon(cache_root: Path, key: str) -> Path | None:
    for suffix in sorted(_IMAGE_SUFFIXES):
        path = cache_root / f"{key}{suffix}"
        if not path.is_file():
            continue
        try:
            with path.open("rb") as handle:
                header = handle.read(12)
            if _image_kind(header):
                return path
            path.unlink()
        except OSError:
            continue
    return None


def _store_icon(data: bytes, key: str, cache_root: Path) -> Path | None:
    suffix = _image_kind(data)
    if not suffix:
        return None
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        destination = cache_root / f"{key}{suffix}"
        fd, temporary = tempfile.mkstemp(prefix=f".{key}-", dir=cache_root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(destination)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        return destination
    except OSError:
        return None


def _candidate_score(item: zipfile.ZipInfo) -> tuple[int, int, int]:
    path = PurePosixPath(item.filename)
    stem = path.stem.casefold()
    name_score = _ICON_NAMES.get(stem, 0)
    if not name_score and not re.search(r"(^|[_-])(launcher|app[_-]?icon)([_-]|$)", stem):
        return (0, 0, 0)
    if not name_score:
        name_score = 10
    parent = path.parent.name.casefold()
    density = next(
        (score for label, score in _DENSITY_SCORES.items() if label in parent),
        0,
    )
    return (name_score, density, min(item.file_size, 20 * 1024 * 1024))


def cache_apk_icon(apk: Path, display_name: str, cache_root: Path) -> Path | None:
    """Cache a likely launcher image without decoding or modifying the APK.

    The cache is keyed by normalized display name, so renamed builds with different
    Android IDs can reuse one icon. Unknown or adaptive-only icons simply fall back
    to the neutral tile in the UI.
    """
    if not display_name.strip() or not apk.is_file():
        return None
    key = display_name_key(display_name)
    if existing := _existing_icon(cache_root, key):
        return existing
    try:
        with zipfile.ZipFile(apk) as archive:
            candidates = [
                item
                for item in archive.infolist()
                if not item.is_dir()
                and item.file_size <= 20 * 1024 * 1024
                and PurePosixPath(item.filename).suffix.casefold() in _IMAGE_SUFFIXES
                and item.filename.replace("\\", "/").startswith("res/")
                and _candidate_score(item)[0]
            ]
            if not candidates:
                return None
            selected = max(candidates, key=_candidate_score)
            data = archive.read(selected)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    return _store_icon(data, key, cache_root)


def decoded_app_label(decoded: Path) -> str:
    """Resolve the default Android application label from a full Apktool decode."""
    try:
        application = ET.parse(decoded / "AndroidManifest.xml").getroot().find(
            "application"
        )
    except (OSError, ET.ParseError):
        return ""
    if application is None:
        return ""
    raw = application.get(f"{_ANDROID}label", "").strip()
    match = re.fullmatch(r"@(?:[^:]+:)?string/([A-Za-z0-9_.]+)", raw)
    if match is None:
        return raw if raw and not raw.startswith("@") else ""
    resource_name = match.group(1)
    values = decoded / "res" / "values"
    for path in sorted(values.glob("*.xml")) if values.is_dir() else ():
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        for node in root.findall("string"):
            if node.get("name") == resource_name:
                return "".join(node.itertext()).strip()
    return ""


def _decoded_icon_reference(decoded: Path) -> str:
    try:
        application = ET.parse(decoded / "AndroidManifest.xml").getroot().find(
            "application"
        )
    except (OSError, ET.ParseError):
        return ""
    if application is None:
        return ""
    return (
        application.get(f"{_ANDROID}icon", "")
        or application.get(f"{_ANDROID}roundIcon", "")
    )


def _density_score(path: Path) -> int:
    parent = path.parent.name.casefold()
    return next(
        (score for label, score in _DENSITY_SCORES.items() if label in parent),
        0,
    )


def _resolve_decoded_icon(
    decoded: Path,
    reference: str,
    visited: set[str] | None = None,
) -> Path | None:
    match = re.fullmatch(
        r"@(?:[^:]+:)?(mipmap|drawable)/([A-Za-z0-9_.]+)", reference.strip()
    )
    if match is None:
        return None
    visited = visited or set()
    if reference in visited:
        return None
    visited.add(reference)
    resource_type, name = match.groups()
    candidates = sorted((decoded / "res").glob(f"{resource_type}*/{name}.*"))
    raster = [path for path in candidates if path.suffix.casefold() in _IMAGE_SUFFIXES]
    if raster:
        return max(raster, key=lambda path: (_density_score(path), path.stat().st_size))
    for xml_path in (path for path in candidates if path.suffix.casefold() == ".xml"):
        try:
            root = ET.parse(xml_path).getroot()
        except (OSError, ET.ParseError):
            continue
        references = {
            value
            for node in root.iter()
            for value in node.attrib.values()
            if value.startswith("@")
        }
        for nested in sorted(references):
            if resolved := _resolve_decoded_icon(decoded, nested, visited):
                return resolved
    return None


def cache_decoded_app_icon(
    decoded: Path,
    display_name: str,
    cache_root: Path,
) -> Path | None:
    """Cache the manifest-selected launcher icon from decoded Android resources."""
    if not display_name.strip():
        return None
    key = display_name_key(display_name)
    if existing := _existing_icon(cache_root, key):
        return existing
    try:
        source = _resolve_decoded_icon(decoded, _decoded_icon_reference(decoded))
        if source is None:
            return None
        return _store_icon(source.read_bytes(), key, cache_root)
    except OSError:
        return None
