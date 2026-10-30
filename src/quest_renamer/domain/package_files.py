"""Discover auxiliary game data within a single package directory."""

from __future__ import annotations

import os
from pathlib import Path

from quest_renamer.domain.package_ids import is_valid_package_id


def package_extra_files(root: Path, package: str) -> tuple[Path, ...]:
    if not package:
        return ()
    if package != package.strip() or not is_valid_package_id(package):
        raise ValueError("The game data package ID is invalid.")
    folder = root / package
    if folder.is_symlink() or not folder.is_dir():
        return ()
    found: list[Path] = []

    def failed(error: OSError) -> None:
        raise error

    for directory, folders, names in os.walk(folder, followlinks=False, onerror=failed):
        folders[:] = sorted(
            name for name in folders if not (Path(directory) / name).is_symlink()
        )
        for name in sorted(names):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file() or path.suffix.lower() == ".obb":
                continue
            validate_extra_path(path, folder)
            found.append(path)
    return tuple(sorted(found))


def validate_extra_path(path: Path, folder: Path) -> str:
    """Reject escape paths and symlinks, including symlinked ancestors."""
    relative = path.relative_to(folder)
    if not relative.parts or any(part in ("..", ".") for part in relative.parts):
        raise ValueError("An extra game file has an unsafe relative path.")
    current = folder
    for part in ("", *relative.parts):
        current = current / part
        if current.is_symlink():
            raise ValueError("An extra game file uses a symbolic link.")
    if not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError("An extra game file escapes the package folder.")
    return relative.as_posix()
