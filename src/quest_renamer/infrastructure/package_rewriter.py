"""Application-ID rewriting for decoded Android technical files.

Only the *application ID* changes: the manifest ``package`` attribute, provider
authorities, custom permissions, intent actions, and the same identity strings in
resources and code. Java classes keep their original names so native libraries
(JNI exports and ``FindClass`` lookups), reflection, and layout inflation keep
working; the manifest is adjusted so its components still point at those classes.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.build import PackageRewriteReport
from quest_renamer.domain.operations import CancellationToken
from quest_renamer.domain.package_ids import is_valid_package_id
from quest_renamer.infrastructure.reference_scanner import (
    MAX_SCAN_SIZE,
    PackagePatterns,
    collect_java_paths,
    count_file_patterns,
    find_jni_libraries,
    is_technical_file,
    iter_decoded_files,
)

MANIFEST_NAME = "AndroidManifest.xml"

# Elements whose android:name is a class that may be written relative to the package.
_COMPONENT_ELEMENT = re.compile(
    r"<(?:application|activity|activity-alias|service|receiver|provider|instrumentation)"
    r"\b[^>]*>",
    re.DOTALL,
)
_NAME_ATTRIBUTE = re.compile(r'(\bandroid:name=")([^"]*)(")')
# Attributes that always hold a (possibly relative) class name, on any element.
_CLASS_ATTRIBUTE = re.compile(
    r'(\bandroid:(?:targetActivity|parentActivityName|backupAgent|appComponentFactory'
    r'|zygotePreloadName)=")([^"]*)(")'
)
# <meta-data android:name="android.support.PARENT_ACTIVITY" android:value=".Parent"/>
_META_DATA_ELEMENT = re.compile(r"<meta-data\b[^>]*>", re.DOTALL)
_PARENT_ACTIVITY_NAMES = {"android.support.PARENT_ACTIVITY", "androidx.core.PARENT_ACTIVITY"}
_VALUE_ATTRIBUTE = re.compile(r'(\bandroid:value=")([^"]*)(")')
# Values that name *other* packages or classes and must never be rewritten.
_QUERIES_BLOCK = re.compile(r"<queries\b.*?</queries>", re.DOTALL)
_PACKAGE_NAME_ELEMENT = re.compile(r'(<package\b[^>]*\bandroid:name=")([^"]*)(")')
_TARGET_PACKAGE = re.compile(r'(\bandroid:targetPackage=")([^"]*)(")')
_PLACEHOLDER = re.compile(rb"\x00(\d+)\x00")


def qualify_class_name(value: str, package: str) -> str:
    """Expand a manifest class name the way the package manager would.

    ``.Main`` and ``Main`` resolve against the package; anything containing a dot
    is already fully qualified.
    """
    if not value:
        return value
    if value.startswith("."):
        return package + value
    if "." not in value:
        return f"{package}.{value}"
    return value


def qualify_manifest_components(text: str, package: str) -> tuple[str, int]:
    """Make every component class name in a decoded manifest fully qualified.

    Android resolves relative names against the manifest ``package``. Once that
    attribute changes, ``.MainActivity`` would point at a class that does not exist,
    so relative names are expanded against the *original* package before the
    identity is rewritten. Returns the new text and the number of names expanded.
    """
    expanded = 0

    def qualify(match: re.Match[str]) -> str:
        nonlocal expanded
        value = match.group(2)
        qualified = qualify_class_name(value, package)
        if qualified != value:
            expanded += 1
        return f"{match.group(1)}{qualified}{match.group(3)}"

    def fix_element(match: re.Match[str]) -> str:
        return _NAME_ATTRIBUTE.sub(qualify, match.group(0))

    def fix_meta_data(match: re.Match[str]) -> str:
        element = match.group(0)
        name = _NAME_ATTRIBUTE.search(element)
        if name is None or name.group(2) not in _PARENT_ACTIVITY_NAMES:
            return element
        return _VALUE_ATTRIBUTE.sub(qualify, element)

    text = _COMPONENT_ELEMENT.sub(fix_element, text)
    text = _CLASS_ATTRIBUTE.sub(qualify, text)
    text = _META_DATA_ELEMENT.sub(fix_meta_data, text)
    return text, expanded


def protect_manifest_values(text: str, package: str) -> tuple[str, list[str]]:
    """Replace class names and foreign package names with placeholders.

    Component classes (whatever their shape: ``.NDK``, ``.a.b``), class-valued
    attributes, ``PARENT_ACTIVITY`` meta-data, ``<queries><package>`` entries and
    ``android:targetPackage`` (unless it is the app itself) keep their exact text.
    ``restore_manifest_values`` puts them back after the identity rewrite.
    """
    saved: list[str] = []

    def keep(match: re.Match[str]) -> str:
        saved.append(match.group(2))
        return f"{match.group(1)}\x00{len(saved) - 1}\x00{match.group(3)}"

    def keep_component(match: re.Match[str]) -> str:
        return _NAME_ATTRIBUTE.sub(keep, match.group(0))

    def keep_meta_data(match: re.Match[str]) -> str:
        element = match.group(0)
        name = _NAME_ATTRIBUTE.search(element)
        if name is None or name.group(2) not in _PARENT_ACTIVITY_NAMES:
            return element
        return _VALUE_ATTRIBUTE.sub(keep, element)

    def keep_foreign_package(match: re.Match[str]) -> str:
        if match.group(2) == package:
            return match.group(0)
        return keep(match)

    def keep_queries(match: re.Match[str]) -> str:
        return _PACKAGE_NAME_ELEMENT.sub(keep_foreign_package, match.group(0))

    text = _COMPONENT_ELEMENT.sub(keep_component, text)
    text = _CLASS_ATTRIBUTE.sub(keep, text)
    text = _META_DATA_ELEMENT.sub(keep_meta_data, text)
    text = _QUERIES_BLOCK.sub(keep_queries, text)
    text = _TARGET_PACKAGE.sub(keep_foreign_package, text)
    return text, saved


def restore_manifest_values(data: bytes, saved: list[str]) -> bytes:
    return _PLACEHOLDER.sub(lambda m: saved[int(m.group(1))].encode("utf-8"), data)


def replace_package_references(
    decoded: Path,
    old: str,
    new: str,
    *,
    token: CancellationToken,
    log: Callable[[str], None] | None = None,
    rename_java_packages: bool = False,
) -> PackageRewriteReport:
    """Rewrite identity references to ``old`` inside Android technical files.

    Java namespace references (class descriptors, paths, and dotted class names)
    are counted but never modified unless ``rename_java_packages`` is set, and that
    legacy mode is refused when a native library exports JNI methods for the
    package. Game data (assets, native libraries, compiled code) is scanned and
    reported but never modified. Token boundaries guarantee that
    ``com.example.gamepad`` is left alone when ``com.example.game`` is renamed.
    """
    if not is_valid_package_id(old):
        raise ValueError("The source package ID is empty or invalid; nothing was rewritten.")
    if not is_valid_package_id(new):
        raise ValueError("The new package ID is empty or invalid; nothing was rewritten.")
    patterns = PackagePatterns.for_package(old, collect_java_paths(decoded, old))
    jni_libraries = find_jni_libraries(decoded, old, token)
    if rename_java_packages and jni_libraries:
        raise ValueError(
            "Renaming the Java packages would break this app: its native code binds to "
            f"classes in {old} ({', '.join(jni_libraries[:3])}"
            + (f" and {len(jni_libraries) - 3} more" if len(jni_libraries) > 3 else "")
            + "). Turn off “Also rename Java packages” in Settings and build again."
        )
    if jni_libraries and log:
        count = len(jni_libraries)
        log(
            f"{count} native {'library exports' if count == 1 else 'libraries export'} "
            f"JNI methods for {old}; Java class names are kept so they still bind."
        )
    changed_files = 0
    changed_occurrences = 0
    namespace_references = 0
    qualified_components = 0
    preserved: list[str] = []

    for path, relative, size in iter_decoded_files(decoded):
        token.raise_if_cancelled()
        if size > MAX_SCAN_SIZE:
            continue
        if is_technical_file(relative):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            saved: list[str] = []
            if relative == MANIFEST_NAME:
                text, qualified_components = qualify_manifest_components(
                    data.decode("utf-8", errors="surrogateescape"), old
                )
                if not rename_java_packages:
                    text, saved = protect_manifest_values(text, old)
                data = text.encode("utf-8", errors="surrogateescape")
            updated, occurrences, namespace = patterns.rewrite(
                data, new, namespace=rename_java_packages
            )
            if saved:
                updated = restore_manifest_values(updated, saved)
            namespace_references += namespace
            if not occurrences and not (relative == MANIFEST_NAME and qualified_components):
                continue
            path.write_bytes(updated)
            changed_files += 1
            changed_occurrences += occurrences
            continue
        counts = count_file_patterns(path, patterns, token, max_size=MAX_SCAN_SIZE, size=size)
        if counts is None or not sum(counts):
            continue
        preserved.append(relative)

    if log:
        if rename_java_packages:
            log(
                f"Updated {changed_occurrences} package reference(s), Java packages "
                f"included, in {changed_files} Android technical file(s)."
            )
        else:
            log(
                f"Updated {changed_occurrences} application-ID reference(s) in "
                f"{changed_files} Android technical file(s); "
                f"{namespace_references} Java class reference(s) kept for native-code "
                "compatibility."
            )
        if qualified_components:
            log(
                f"Expanded {qualified_components} relative component name(s) in the "
                "manifest so they still point at the original classes."
            )
        if preserved:
            log(
                "Preserved matching game data outside Android technical files: "
                + ", ".join(preserved[:3])
                + (f" and {len(preserved) - 3} more" if len(preserved) > 3 else "")
            )
    return PackageRewriteReport(
        changed_files=changed_files,
        changed_occurrences=changed_occurrences,
        preserved_files=tuple(preserved),
        namespace_references=namespace_references,
        qualified_components=qualified_components,
        jni_libraries=jni_libraries,
        java_packages_renamed=rename_java_packages,
    )
