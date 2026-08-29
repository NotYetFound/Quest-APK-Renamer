"""Bounded-memory, boundary-aware package-reference scanning for decoded APK files.

The scanner and the rewriter share one definition of "a reference to package X" so
that the Inspector preview and the real rewrite always agree.

A reference is the package ID as a whole token: ``com.example.game`` and its
sub-packages (``com.example.game.ui``) match, while ``com.example.gamepad`` or
``org.foo.com.example.game`` do not. Each reference is then classified:

* **Identity references** name the *application ID*: the bare package, content
  provider authorities (``com.example.game.fileprovider``), custom permissions
  (``com.example.game.permission.C2D_MESSAGE``), intent actions
  (``com.example.game.ACTION_PLAY``) and similar. These are rewritten, because the
  renamed copy must not collide with the original app on the headset.
* **Namespace references** name Java code: JVM descriptors and paths
  (``Lcom/example/game/Main;``, ``com/example/game``) and dotted class names
  (``com.example.game.MainActivity``, ``com.example.game.ui.Widget``). These are
  never rewritten. Native libraries bind to Java classes by their original names
  (``Java_com_example_game_Main_nativeInit`` exports and ``FindClass`` lookups),
  so moving the classes breaks every app with its own JNI code at launch.

The dotted form is told apart by its continuation: a segment that looks like a
class name (starts with an upper-case letter and is not an ALL_CAPS constant, or
contains ``$``) marks a Java reference; anything else is part of the app identity.
"""

from __future__ import annotations

import os
import re
import stat as stat_module
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken

SCAN_CHUNK_SIZE = 4 * 1024 * 1024
MAX_SCAN_SIZE = 64 * 1024 * 1024
TECHNICAL_XML_ROOTS = frozenset({"res"})
# Bytes of look-ahead kept past a chunk boundary so a dotted reference's class-name
# continuation can still be classified; class paths longer than this are unheard of.
_CONTINUATION_CONTEXT = 512

_IDENT = rb"A-Za-z0-9_"
_IDENT_BYTES = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_DOTTED_STOP = _IDENT_BYTES | {ord(".")}
_SLASHED_STOP = _IDENT_BYTES | {ord("/")}
# Bytes of look-behind context a chunk needs: a boundary byte plus the JVM ``L``.
_LOOKBEHIND_CONTEXT = 2


def _dotted_boundary(data: bytes, start: int, continuation: bytes = b"") -> bool:
    """Not preceded by an identifier char or a dot (that would be another package).

    The one legitimate dot-preceded form is an expansion-file name
    (``main.1.com.example.game.obb``), where the package sits between the version
    tag and the ``.obb`` extension.
    """
    if start == 0:
        return True
    previous = data[start - 1]
    if previous not in _DOTTED_STOP:
        return True
    return previous == ord(".") and continuation.lower() == b".obb"


def _slashed_boundary(data: bytes, start: int) -> bool:
    """JVM descriptors prefix the path with ``L`` (``Lcom/example/game/Main;``) or
    ``[L`` for arrays; any other preceding identifier char or slash means the bytes
    belong to a longer, unrelated path."""
    if start == 0:
        return True
    previous = data[start - 1]
    if previous not in _SLASHED_STOP:
        return True
    if previous != ord("L"):
        return False
    return start == 1 or data[start - 2] not in _SLASHED_STOP


def _segment_names_java(segment: bytes) -> bool:
    """Whether one dotted continuation segment looks like a Java class or type."""
    if b"$" in segment:
        return True
    first = segment[:1]
    if not first.isupper():
        return False
    if len(segment) <= 2:
        # ``R``, ``UI`` and similar short names are types, not identity constants.
        return True
    # ``ACTION_PLAY`` / ``C2D_MESSAGE`` are identity constants; ``MainActivity`` is code.
    return any(byte.islower() for byte in segment.decode("ascii", "replace"))


def is_java_continuation(continuation: bytes) -> bool:
    """Whether the text following a package match names Java code (``.ui.Main``)."""
    return any(_segment_names_java(part) for part in continuation.split(b".") if part)


@dataclass(frozen=True, slots=True)
class PackagePatterns:
    """Compiled byte patterns for one package ID in dotted and slashed (JVM) form.

    ``java_paths`` optionally lists slashed class and package paths that exist in
    the decoded code (``com/example/game/NDK``, ``com/example/game/a``); a dotted
    continuation naming one of them is Java even when its shape looks like an
    identity constant (ALL_CAPS or obfuscated one-letter names).
    """

    package: str
    dotted: re.Pattern[bytes]
    slashed: re.Pattern[bytes] | None
    java_paths: frozenset[bytes] = frozenset()

    @classmethod
    def for_package(
        cls, package: str, java_paths: frozenset[bytes] = frozenset()
    ) -> PackagePatterns:
        if not package:
            raise ValueError("A package ID is required.")
        dotted_bytes = re.escape(package.encode("utf-8"))
        # Patterns start with the literal package so ``re`` can use its fast prefix
        # scan; the look-behind boundary is checked in ``_dotted_boundary`` /
        # ``_slashed_boundary`` instead, which keeps multi-megabyte files quick.
        # Not followed by an identifier char (com.example.gamepad must not match);
        # the optional continuation captures sub-package / class segments so the
        # match can be classified as identity or Java namespace.
        dotted = re.compile(
            dotted_bytes + rb"(?![" + _IDENT + rb"])((?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)"
        )
        slashed: re.Pattern[bytes] | None = None
        if "." in package:
            slashed_bytes = re.escape(package.replace(".", "/").encode("utf-8"))
            slashed = re.compile(slashed_bytes + rb"(?![" + _IDENT + rb"])")
        return cls(package, dotted, slashed, java_paths)

    @property
    def longest(self) -> int:
        return len(self.package.encode("utf-8"))

    def names_java(self, continuation: bytes) -> bool:
        """Whether a dotted continuation names Java code rather than the app identity."""
        if is_java_continuation(continuation):
            return True
        if not self.java_paths or not continuation:
            return False
        path = self.package.replace(".", "/").encode("utf-8") + continuation.split(b"$", 1)[
            0
        ].replace(b".", b"/")
        return path in self.java_paths

    def iter_matches(self, data: bytes) -> Iterator[tuple[int, bool]]:
        """Yield ``(start, is_identity)`` for every reference in ``data``."""
        for match in self.dotted.finditer(data):
            if _dotted_boundary(data, match.start(), match.group(1)):
                yield match.start(), not self.names_java(match.group(1))
        if self.slashed is not None:
            for match in self.slashed.finditer(data):
                if _slashed_boundary(data, match.start()):
                    yield match.start(), False

    def count(self, data: bytes) -> tuple[int, int]:
        """Return ``(identity, namespace)`` reference counts."""
        identity = 0
        namespace = 0
        for _start, is_identity in self.iter_matches(data):
            if is_identity:
                identity += 1
            else:
                namespace += 1
        return identity, namespace

    def substitute(self, data: bytes, new_package: str) -> tuple[bytes, int]:
        """Rewrite identity references only; return the new bytes and the count."""
        updated, changed, _kept = self.rewrite(data, new_package)
        return updated, changed

    def rewrite(
        self, data: bytes, new_package: str, *, namespace: bool = False
    ) -> tuple[bytes, int, int]:
        """Rewrite references; return ``(bytes, changed, namespace_kept)``.

        By default only identity references change. With ``namespace=True`` the
        Java namespace moves as well (legacy behaviour: class descriptors, paths and
        dotted class names) — only safe for apps without JNI code of their own.
        Files without any match are returned untouched without a copy.
        """
        replacement = new_package.encode("utf-8")
        changed = 0
        kept = 0

        def swap(match: re.Match[bytes]) -> bytes:
            nonlocal changed, kept
            continuation = match.group(1)
            if not _dotted_boundary(data, match.start(), continuation):
                return match.group(0)
            if not namespace and self.names_java(continuation):
                kept += 1
                return match.group(0)
            changed += 1
            return replacement + continuation

        updated = self.dotted.sub(swap, data) if self.dotted.search(data) else data
        if self.slashed is None:
            return updated, changed, kept
        if namespace:
            slashed_replacement = new_package.replace(".", "/").encode("utf-8")

            def swap_slashed(match: re.Match[bytes]) -> bytes:
                nonlocal changed
                if not _slashed_boundary(match.string, match.start()):
                    return match.group(0)
                changed += 1
                return slashed_replacement

            updated = self.slashed.sub(swap_slashed, updated)
        else:
            kept += sum(
                1
                for match in self.slashed.finditer(data)
                if _slashed_boundary(data, match.start())
            )
        return updated, changed, kept


def jni_export_prefix(package: str) -> bytes:
    """The ``Java_<package>_`` prefix native libraries export for JNI methods.

    Mangling follows the JNI specification: ``.`` → ``_``, ``_`` → ``_1``, and any
    other non-ASCII-alphanumeric character → ``_0XXXX``.
    """
    parts: list[str] = []
    for char in package:
        if char == ".":
            parts.append("_")
        elif char == "_":
            parts.append("_1")
        elif char.isascii() and char.isalnum():
            parts.append(char)
        else:
            parts.append(f"_0{ord(char):04x}")
    return ("Java_" + "".join(parts) + "_").encode("ascii")


def find_jni_libraries(
    decoded: Path,
    package: str,
    token: CancellationToken,
    *,
    max_size: int = 1024 * 1024 * 1024,
) -> tuple[str, ...]:
    """Native libraries that bind to Java classes inside ``package``.

    Both directions count: exported ``Java_<package>_…`` methods and slashed class
    paths used for ``FindClass``/``GetMethodID`` lookups. Renaming the Java
    namespace would leave those unresolved and crash the app at launch.
    """
    patterns = (jni_export_prefix(package), package.replace(".", "/").encode("utf-8") + b"/")
    found: list[str] = []
    for path, relative, size in iter_decoded_files(decoded / "lib"):
        token.raise_if_cancelled()
        if not relative.lower().endswith(".so"):
            continue
        counts = count_file_patterns(path, patterns, token, max_size=max_size, size=size)
        if counts and any(counts):
            found.append("lib/" + relative)
    return tuple(found)


def collect_java_paths(decoded: Path, package: str) -> frozenset[bytes]:
    """Slashed paths of every class and package directory under ``package`` in smali."""
    relative = package.replace(".", "/")
    paths: set[bytes] = set()
    try:
        roots = [
            entry
            for entry in decoded.iterdir()
            if entry.is_dir() and entry.name.startswith("smali")
        ]
    except OSError:
        return frozenset()
    for root in roots:
        base = root / relative
        if not base.is_dir():
            continue
        for current, _dirs, files in os.walk(base):
            rel_dir = os.path.relpath(current, root).replace(os.sep, "/")
            paths.add(rel_dir.encode("utf-8"))
            for name in files:
                if name.endswith(".smali"):
                    paths.add(f"{rel_dir}/{name[:-6]}".encode())
    return frozenset(paths)


def is_technical_file(relative_posix: str) -> bool:
    """Android technical files are rewritten; everything else is preserved game data."""
    if relative_posix in {"AndroidManifest.xml", "apktool.yml"}:
        return True
    lower = relative_posix.lower()
    if lower.endswith(".smali"):
        return True
    head, separator, _rest = relative_posix.partition("/")
    return bool(separator and head in TECHNICAL_XML_ROOTS and lower.endswith(".xml"))


def iter_decoded_files(decoded: Path) -> Iterator[tuple[Path, str, int]]:
    """Yield ``(path, relative_posix, size)`` for regular files with one stat each.

    ``os.walk`` with ``DirEntry`` avoids the three or four ``stat`` calls per file
    that ``Path.rglob`` + ``is_file`` + ``is_symlink`` + ``stat`` would cost on
    large Unity/Unreal decodes.
    """
    root = str(decoded)
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        relative_dir = os.path.relpath(current, root)
        prefix = "" if relative_dir == "." else relative_dir.replace(os.sep, "/") + "/"
        for name in sorted(files):
            full = os.path.join(current, name)
            try:
                stat = os.lstat(full)
            except OSError:
                continue
            if not stat_module.S_ISREG(stat.st_mode):
                continue
            yield Path(full), prefix + name, stat.st_size


def count_file_patterns(
    path: Path,
    patterns: tuple[bytes, ...] | PackagePatterns,
    token: CancellationToken,
    *,
    max_size: int,
    chunk_size: int = SCAN_CHUNK_SIZE,
    size: int | None = None,
) -> tuple[int, ...] | None:
    """Count non-overlapping patterns without loading the whole file.

    ``None`` means the file could not safely be scanned or exceeded the caller's
    limit. A small overlap preserves matches split across read boundaries. Plain
    byte patterns count raw substrings; ``PackagePatterns`` applies token
    boundaries and returns ``(identity, namespace)`` counts.
    """
    if isinstance(patterns, tuple) and (
        not patterns or any(not pattern for pattern in patterns)
    ):
        raise ValueError("At least one non-empty byte pattern is required.")
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive.")
    try:
        file_size = path.stat().st_size if size is None else size
        if file_size > max_size:
            return None
        if isinstance(patterns, PackagePatterns):
            # Keep enough overlap that a boundary char either side and the class-name
            # continuation of a reference starting before the cutoff stay visible.
            overlap = patterns.longest + _CONTINUATION_CONTEXT
            if file_size <= chunk_size:
                return patterns.count(path.read_bytes())
            return _count_chunked_regex(path, patterns, token, chunk_size, overlap)
        overlap = max(len(pattern) for pattern in patterns) - 1
        counts = [0] * len(patterns)
        carry = b""
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                token.raise_if_cancelled()
                data = carry + chunk
                cutoff = max(0, len(data) - overlap)
                for index, pattern in enumerate(patterns):
                    position = 0
                    while (found := data.find(pattern, position)) >= 0 and found < cutoff:
                        counts[index] += 1
                        position = found + len(pattern)
                carry = data[cutoff:]
        for index, pattern in enumerate(patterns):
            counts[index] += carry.count(pattern)
        return tuple(counts)
    except OSError:
        return None


def _count_chunked_regex(
    path: Path,
    patterns: PackagePatterns,
    token: CancellationToken,
    chunk_size: int,
    overlap: int,
) -> tuple[int, int]:
    """Count boundary-aware matches across chunks, each reference exactly once.

    A match is counted in the chunk where it *starts*, provided it starts before the
    carry region (so its end, its continuation, and one look-ahead byte are
    present). Two extra bytes of context are carried so the next chunk can still
    evaluate the look-behind (boundary byte plus JVM ``L``) for a match that begins
    right at the carry boundary.
    """
    identity_total = 0
    namespace_total = 0
    carry = b""
    lead = 0  # bytes at the start of ``data`` that only provide look-behind context
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            token.raise_if_cancelled()
            data = carry + chunk
            cutoff = max(lead, len(data) - overlap)
            for start, is_identity in patterns.iter_matches(data):
                if lead <= start < cutoff:
                    if is_identity:
                        identity_total += 1
                    else:
                        namespace_total += 1
            keep_from = max(0, cutoff - _LOOKBEHIND_CONTEXT)
            carry = data[keep_from:]
            lead = cutoff - keep_from
    for start, is_identity in patterns.iter_matches(carry):
        if start >= lead:
            if is_identity:
                identity_total += 1
            else:
                namespace_total += 1
    return identity_total, namespace_total
