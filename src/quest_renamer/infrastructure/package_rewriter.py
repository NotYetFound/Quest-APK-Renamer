"""Conservative package-ID rewriting for decoded Android technical files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.build import PackageRewriteReport
from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.reference_scanner import count_file_patterns

MAX_SCAN_SIZE = 64 * 1024 * 1024


def _is_technical_file(relative: Path) -> bool:
    return (
        relative.as_posix() in {"AndroidManifest.xml", "apktool.yml"}
        or relative.suffix.lower() == ".smali"
        or (
            len(relative.parts) > 1
            and relative.parts[0] == "res"
            and relative.suffix.lower() == ".xml"
        )
    )


def replace_package_references(
    decoded: Path,
    old: str,
    new: str,
    *,
    token: CancellationToken,
    log: Callable[[str], None] | None = None,
) -> PackageRewriteReport:
    old_dotted = old.encode("utf-8")
    new_dotted = new.encode("utf-8")
    old_slashed = old.replace(".", "/").encode("utf-8")
    new_slashed = new.replace(".", "/").encode("utf-8")
    changed_files = 0
    changed_occurrences = 0
    preserved: list[str] = []

    for path in decoded.rglob("*"):
        token.raise_if_cancelled()
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(decoded)
        technical = _is_technical_file(relative)
        data = b""
        if technical:
            try:
                if path.stat().st_size > MAX_SCAN_SIZE:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            dotted_count = data.count(old_dotted)
            slashed_count = data.count(old_slashed) if old_slashed != old_dotted else 0
        else:
            patterns = (
                (old_dotted, old_slashed)
                if old_slashed != old_dotted
                else (old_dotted,)
            )
            counts = count_file_patterns(
                path,
                patterns,
                token,
                max_size=MAX_SCAN_SIZE,
            )
            if counts is None:
                continue
            dotted_count = counts[0]
            slashed_count = counts[1] if len(counts) > 1 else 0
        occurrences = dotted_count + slashed_count
        if not occurrences:
            continue
        if not technical:
            preserved.append(relative.as_posix())
            continue
        updated = data.replace(old_dotted, new_dotted)
        if old_slashed != old_dotted:
            updated = updated.replace(old_slashed, new_slashed)
        if updated != data:
            path.write_bytes(updated)
            changed_files += 1
            changed_occurrences += occurrences

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
