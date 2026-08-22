"""Small helpers shared by the QML-facing controllers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1000 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1000
    return f"{value} B"


def local_path_from_url(value: object) -> Path | None:
    """Convert a QML-provided file URL (or plain path) into a local Path."""
    if isinstance(value, QUrl):
        url = value
    else:
        text = str(value)
        if not text:
            return None
        url = QUrl(text)
    local = url.toLocalFile() if url.isLocalFile() else url.toString()
    if not local:
        return None
    return Path(local).expanduser()


def write_system_clipboard(value: str) -> bool:
    """Copy text to the desktop clipboard; False when no GUI session is available."""
    if QGuiApplication.instance() is None:
        return False
    try:
        QGuiApplication.clipboard().setText(value)
    except RuntimeError:
        return False
    return True


def unique_numbered_path(preferred: Path) -> Path:
    """Return ``preferred`` or the first free ``"Name (2)"``-style sibling."""
    if not preferred.exists():
        return preferred
    number = 2
    while True:
        candidate = preferred.with_name(f"{preferred.name} ({number})")
        if not candidate.exists():
            return candidate
        number += 1
