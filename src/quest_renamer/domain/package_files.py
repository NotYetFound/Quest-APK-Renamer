"""Discover auxiliary game data within a single package directory."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from quest_renamer.domain.package_ids import is_valid_package_id


def package_extra_files(root: Path, package: str) -> tuple[Path, ...]:
    if not package:
        return ()
    if package != package.strip() or not is_valid_package_id(package):
        raise ValueError("The game data package ID is invalid.")
    folder = root / package
    try:
        info = folder.lstat()
    except FileNotFoundError:
        return ()
    if _is_link(info) or not stat.S_ISDIR(info.st_mode):
        return ()
    found: list[Path] = []
    pending = [folder]
    while pending:
        directory = pending.pop()
        if directory != folder:
            validate_extra_path(directory, folder)
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                # Windows junctions and other reparse points can redirect a traversal.
                if os.name == "nt" and _is_link(entry.stat(follow_symlinks=False)):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(directory / entry.name)
                elif not entry.name.lower().endswith(".obb") and entry.is_file(
                    follow_symlinks=False
                ):
                    found.append(directory / entry.name)
    return tuple(sorted(found))


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def validate_extra_path(path: Path, folder: Path) -> str:
    """Reject escape paths and symlinks, including symlinked ancestors."""
    relative = path.relative_to(folder)
    if not relative.parts or any(part in ("..", ".") for part in relative.parts):
        raise ValueError("An extra game file has an unsafe relative path.")
    current = folder
    for part in ("", *relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        if _is_link(info):
            raise ValueError("An extra game file uses a symbolic link.")
    if not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError("An extra game file escapes the package folder.")
    return relative.as_posix()
