"""Bounded-memory byte-pattern scanning for decoded APK files."""

from __future__ import annotations

from pathlib import Path

from quest_renamer.domain.operations import CancellationToken

SCAN_CHUNK_SIZE = 1024 * 1024


def count_file_patterns(
    path: Path,
    patterns: tuple[bytes, ...],
    token: CancellationToken,
    *,
    max_size: int,
    chunk_size: int = SCAN_CHUNK_SIZE,
) -> tuple[int, ...] | None:
    """Count non-overlapping patterns without loading the whole file.

    ``None`` means the file could not safely be scanned or exceeded the caller's
    limit. A small overlap preserves matches split across read boundaries.
    """
    if not patterns or any(not pattern for pattern in patterns):
        raise ValueError("At least one non-empty byte pattern is required.")
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive.")
    try:
        if path.stat().st_size > max_size:
            return None
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
