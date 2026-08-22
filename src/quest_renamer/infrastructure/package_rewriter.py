"""Conservative package-ID rewriting for decoded Android technical files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.build import PackageRewriteReport
from quest_renamer.domain.operations import CancellationToken
from quest_renamer.domain.package_ids import is_valid_package_id
from quest_renamer.infrastructure.reference_scanner import (
    MAX_SCAN_SIZE,
    PackagePatterns,
    count_file_patterns,
    is_technical_file,
    iter_decoded_files,
)


def _is_technical_file(relative: Path) -> bool:
    return is_technical_file(relative.as_posix())


def replace_package_references(
    decoded: Path,
    old: str,
    new: str,
    *,
    token: CancellationToken,
    log: Callable[[str], None] | None = None,
) -> PackageRewriteReport:
    """Rewrite whole-token references to ``old`` inside Android technical files.

    Game data (assets, native libraries, compiled code) is scanned and reported but
    never modified. Token boundaries guarantee that ``com.example.gamepad`` is left
    alone when ``com.example.game`` is renamed.
    """
    if not is_valid_package_id(old):
        raise ValueError("The source package ID is empty or invalid; nothing was rewritten.")
    if not is_valid_package_id(new):
        raise ValueError("The new package ID is empty or invalid; nothing was rewritten.")
    patterns = PackagePatterns.for_package(old)
    changed_files = 0
    changed_occurrences = 0
    preserved: list[str] = []

    for path, relative, size in iter_decoded_files(decoded):
        token.raise_if_cancelled()
        if size > MAX_SCAN_SIZE:
            continue
        technical = is_technical_file(relative)
        if technical:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            updated, occurrences = patterns.substitute(data, new)
            if not occurrences:
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
        log(
            f"Updated {changed_occurrences} package reference(s) in "
            f"{changed_files} Android technical file(s)."
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
    )
