"""Cross-platform Trash adapter backed by the Qt runtime already used by the app."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFile


def move_to_trash(path: Path) -> None:
    """Move one exact path to the platform Trash or raise without deleting it."""
    target = path.expanduser().resolve()
    if not target.exists():
        raise OSError(f"The path no longer exists: {target}")
    result = QFile.moveToTrash(str(target))
    success = bool(result[0]) if isinstance(result, tuple) else bool(result)
    if not success:
        raise OSError(f"The operating system could not move {target.name} to Trash.")
