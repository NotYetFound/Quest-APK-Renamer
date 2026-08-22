"""Small bounded activity log suitable for support diagnostics."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

Clock = Callable[[], dt.datetime]


class ActivityLog:
    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        max_view_lines: int = 400,
        clock: Clock | None = None,
    ) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.max_view_lines = max_view_lines
        self._clock = clock or (lambda: dt.datetime.now().astimezone())
        self._lock = threading.Lock()

    def tail(self) -> tuple[str, ...]:
        """Return the last ``max_view_lines`` lines without reading the whole file."""
        try:
            with self.path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                window = 64 * 1024
                data = b""
                # Read backwards in growing windows until enough lines are present.
                while size > 0 and data.count(b"\n") <= self.max_view_lines:
                    read_from = max(0, size - window)
                    handle.seek(read_from)
                    data = handle.read(size - read_from) + data
                    size = read_from
                    window *= 2
        except OSError:
            return ()
        lines = data.decode("utf-8", errors="replace").splitlines()
        if size > 0 and lines:
            # The first line is probably a partial line from the middle of the file.
            lines = lines[1:]
        return tuple(lines[-self.max_view_lines :])

    def append(self, message: str) -> str:
        timestamp = self._timestamp()
        clean_lines = message.rstrip().splitlines() or [""]
        lines = [f"[{timestamp}] [INFO] {clean_lines[0]}"]
        lines.extend(f"    {line}" for line in clean_lines[1:])
        self._write_lines(lines)
        return "\n".join(lines)

    def append_event(
        self,
        category: str,
        title: str,
        details: tuple[tuple[str, str], ...] = (),
    ) -> tuple[str, ...]:
        timestamp = self._timestamp()
        label = category.strip().upper()[:12] or "INFO"
        lines = [f"[{timestamp}] [{label}] {title.strip()}"]
        for name, value in details:
            value_lines = str(value).rstrip().splitlines() or [""]
            lines.append(f"    {name}: {value_lines[0]}")
            lines.extend(f"        {line}" for line in value_lines[1:])
        self._write_lines(lines)
        return tuple(lines)

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC).isoformat(timespec="seconds")

    def _write_lines(self, lines: list[str] | tuple[str, ...]) -> None:
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.is_file() and self.path.stat().st_size > self.max_bytes:
                    previous = self.path.with_suffix(self.path.suffix + ".1")
                    previous.unlink(missing_ok=True)
                    self.path.replace(previous)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write("\n".join(lines) + "\n")
        except OSError:
            pass

    def export(self, destination: Path) -> None:
        destination = destination.expanduser().resolve(strict=False)
        if destination == self.path.resolve(strict=False):
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            with self._lock:
                if self.path.is_file():
                    shutil.copyfile(self.path, temporary)
                else:
                    temporary.write_text("", encoding="utf-8")
                if os.name != "nt":
                    temporary.chmod(0o600)
                os.replace(temporary, destination)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def clear(self) -> None:
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_text("", encoding="utf-8")
                temporary.replace(self.path)
        except OSError:
            pass
