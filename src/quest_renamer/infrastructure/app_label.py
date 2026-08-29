"""Optional display-name changes for a renamed copy (``Game`` → ``Game (Dev)``).

The Android launcher shows ``<application android:label>``; it is either a literal
or a ``@string/`` reference resolved per locale. Both forms are handled on the
decoded Apktool tree without touching any other resource.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from pathlib import Path

MANIFEST_NAME = "AndroidManifest.xml"

_APPLICATION_TAG = re.compile(r"<application\b[^>]*>", re.DOTALL)
_ACTIVITY_TAG = re.compile(r"<(?:activity|activity-alias)\b[^>]*>", re.DOTALL)
_LABEL_ATTRIBUTE = re.compile(r'(\bandroid:label=")([^"]*)(")')
_STRING_REFERENCE = re.compile(r"@(?:string|(?:[^:]+:)?string)/([A-Za-z0-9_.]+)")


class AppLabelError(ValueError):
    """The display name could not be changed on this decoded APK."""


def escape_android_string(text: str) -> str:
    """Escape text for the body of an Android ``<string>`` resource."""
    escaped = html.escape(text, quote=False)
    escaped = escaped.replace("'", "\\'").replace('"', '\\"')
    if escaped.startswith("@") or escaped.startswith("?"):
        escaped = "\\" + escaped
    return escaped


_CDATA = re.compile(r"^\s*<!\[CDATA\[(.*)\]\]>\s*$", re.DOTALL)


def unescape_android_string(body: str) -> str:
    """Undo ``escape_android_string`` for reporting the previous label."""
    cdata = _CDATA.fullmatch(body)
    if cdata is not None:
        return cdata.group(1)
    text = body.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    text = text.replace("\\'", "'").replace('\\"', '"').replace("\\@", "@")
    return html.unescape(text)


def _string_body(previous_body: str, text: str) -> str:
    """Encode ``text`` the way the original body was written (CDATA or escaped)."""
    if _CDATA.fullmatch(previous_body) is not None and "]]>" not in text:
        return f"<![CDATA[{text}]]>"
    return escape_android_string(text)


def escape_manifest_attribute(text: str) -> str:
    return html.escape(text, quote=True)


def _string_element(name: str) -> re.Pattern[str]:
    # ``<string`` followed by whitespace: ``<string-array name="…">`` must not match,
    # and the body may not contain another element start.
    return re.compile(
        r'(<string\s[^>]*?\bname="'
        + re.escape(name)
        + r'"[^>]*>)((?:(?!<string)[^<]|<(?!/?string))*?)(</string>)',
        re.DOTALL,
    )


def resolve_label(
    label: str,
    suffix: str,
    original: str,
) -> str:
    """The final display name: an explicit label wins, else original + suffix."""
    label = label.strip()
    if label:
        return label
    suffix = suffix.strip()
    if suffix and original:
        return f"{original} {suffix}"
    return ""


def apply_app_label(
    decoded: Path,
    *,
    label: str = "",
    suffix: str = "",
    log: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Change the application label; return ``(previous, new)`` or ``("", "")``.

    ``label`` replaces the name outright (every locale); ``suffix`` is appended to
    each locale's own translation so localized copies stay readable.
    """
    if not label.strip() and not suffix.strip():
        return "", ""
    manifest = decoded / MANIFEST_NAME
    try:
        text = manifest.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise AppLabelError(f"The decoded manifest could not be read: {exc}") from exc
    application = _APPLICATION_TAG.search(text)
    if application is None:
        raise AppLabelError("The decoded manifest has no <application> element.")
    attribute = _LABEL_ATTRIBUTE.search(application.group(0))
    if attribute is None:
        raise AppLabelError("The app declares no display name that could be changed.")
    raw = attribute.group(2)

    if raw.startswith("@"):
        reference = _STRING_REFERENCE.fullmatch(raw)
        if reference is None or raw.startswith("@android:"):
            raise AppLabelError(
                f"The display name is a framework resource ({raw}); it cannot be changed."
            )
        return _apply_string_resource(decoded, reference.group(1), label, suffix, log)

    previous = html.unescape(raw)
    new_label = resolve_label(label, suffix, previous)
    if not new_label or new_label == previous:
        return previous, ""
    replacement = escape_manifest_attribute(new_label)

    def swap(match: re.Match[str]) -> str:
        if match.group(2) != raw:
            return match.group(0)
        return f"{match.group(1)}{replacement}{match.group(3)}"

    def fix_element(match: re.Match[str]) -> str:
        return _LABEL_ATTRIBUTE.sub(swap, match.group(0))

    updated = _APPLICATION_TAG.sub(fix_element, text, count=1)
    # Launcher entries show the activity's own label when it repeats the app name.
    updated = _ACTIVITY_TAG.sub(fix_element, updated)
    manifest.write_text(updated, encoding="utf-8", errors="surrogateescape")
    if log:
        log(f"Display name changed in the manifest: {previous!r} → {new_label!r}")
    return previous, new_label


def _apply_string_resource(
    decoded: Path,
    name: str,
    label: str,
    suffix: str,
    log: Callable[[str], None] | None,
) -> tuple[str, str]:
    res = decoded / "res"
    pattern = _string_element(name)
    default_previous = ""
    default_new = ""
    changed_files = 0
    values_dirs = (
        sorted(
            path
            for path in res.iterdir()
            if path.is_dir() and path.name.split("-")[0] == "values"
        )
        if res.is_dir()
        else []
    )
    # Resolve the default translation first so suffix-only locales can fall back.
    for folder in values_dirs:
        for xml in sorted(folder.glob("*.xml")):
            try:
                content = xml.read_text(encoding="utf-8", errors="surrogateescape")
            except OSError:
                continue
            match = pattern.search(content)
            if match is None:
                continue
            previous = unescape_android_string(match.group(2))
            new_label = resolve_label(label, suffix, previous)
            if folder.name == "values":
                default_previous = previous
                default_new = new_label
            if not new_label or new_label == previous:
                continue
            replacement = _string_body(match.group(2), new_label)
            content = content[: match.start(2)] + replacement + content[match.end(2) :]
            xml.write_text(content, encoding="utf-8", errors="surrogateescape")
            changed_files += 1
    if not default_previous and not changed_files:
        raise AppLabelError(
            f"The display name resource @string/{name} was not found in the decoded files."
        )
    if not default_new:
        # No default translation; report the first changed locale instead.
        default_new = resolve_label(label, suffix, default_previous)
    if log and changed_files:
        log(
            f"Display name changed in {changed_files} resource file(s): "
            f"{default_previous!r} → {default_new!r}"
        )
    return default_previous, default_new if changed_files else ""
