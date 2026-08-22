"""Bounded-memory, boundary-aware package-reference scanning for decoded APK files.

The scanner and the rewriter share one definition of "a reference to package X" so
that the Inspector preview and the real rewrite always agree. A reference is the
package ID as a whole token: ``com.example.game`` and its sub-packages
(``com.example.game.ui``) match, while ``com.example.gamepad`` or
``org.foo.com.example.game`` do not.
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

_IDENT = rb"A-Za-z0-9_"


@dataclass(frozen=True, slots=True)
class PackagePatterns:
    """Compiled byte patterns for one package ID in dotted and slashed (JVM) form."""

    package: str
    dotted: re.Pattern[bytes]
    slashed: re.Pattern[bytes] | None

    @classmethod
    def for_package(cls, package: str) -> PackagePatterns:
        if not package:
            raise ValueError("A package ID is required.")
        dotted_bytes = re.escape(package.encode("utf-8"))
        # Not preceded by an identifier char or a dot (that would be another package),
        # and not followed by an identifier char (com.example.gamepad must not match).
        dotted = re.compile(
            rb"(?<![" + _IDENT + rb".])" + dotted_bytes + rb"(?![" + _IDENT + rb"])"
        )
        slashed: re.Pattern[bytes] | None = None
        if "." in package:
            slashed_bytes = re.escape(package.replace(".", "/").encode("utf-8"))
            # JVM descriptors prefix the path with ``L`` (``Lcom/example/game/Main;``)
            # or ``[L`` for arrays; any other preceding identifier char or slash
            # means the bytes belong to a longer, unrelated path.
            slashed = re.compile(
                rb"(?:(?<![/" + _IDENT + rb"])|(?<=(?<![/" + _IDENT + rb"])L))"
                + slashed_bytes
                + rb"(?![" + _IDENT + rb"])"
            )
        return cls(package, dotted, slashed)

    @property
    def longest(self) -> int:
        return len(self.package.encode("utf-8"))

    def count(self, data: bytes) -> tuple[int, int]:
        dotted = sum(1 for _ in self.dotted.finditer(data))
        slashed = sum(1 for _ in self.slashed.finditer(data)) if self.slashed else 0
        return dotted, slashed

    def substitute(self, data: bytes, new_package: str) -> tuple[bytes, int]:
        """Rewrite every reference and return the new bytes with the replacement count."""
        updated, dotted = self.dotted.subn(new_package.encode("utf-8"), data)
        slashed = 0
        if self.slashed is not None:
            updated, slashed = self.slashed.subn(
                new_package.replace(".", "/").encode("utf-8"), updated
            )
        return updated, dotted + slashed


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
    boundaries.
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
            # Keep a generous overlap so a boundary char either side stays visible.
            overlap = patterns.longest + 1
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
    carry region (so its end and one look-ahead byte are present). One extra byte of
    context is carried so the next chunk can still evaluate the look-behind for a
    match that begins right at the carry boundary.
    """
    dotted_total = 0
    slashed_total = 0
    carry = b""
    lead = 0  # bytes at the start of ``data`` that only provide look-behind context
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            token.raise_if_cancelled()
            data = carry + chunk
            cutoff = max(lead, len(data) - overlap)
            for match in patterns.dotted.finditer(data):
                if lead <= match.start() < cutoff:
                    dotted_total += 1
            if patterns.slashed is not None:
                for match in patterns.slashed.finditer(data):
                    if lead <= match.start() < cutoff:
                        slashed_total += 1
            keep_from = max(0, cutoff - 1)
            carry = data[keep_from:]
            lead = cutoff - keep_from
    for match in patterns.dotted.finditer(carry):
        if match.start() >= lead:
            dotted_total += 1
    if patterns.slashed is not None:
        for match in patterns.slashed.finditer(carry):
            if match.start() >= lead:
                slashed_total += 1
    return dotted_total, slashed_total
