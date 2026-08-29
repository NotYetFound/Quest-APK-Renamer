"""Recovery-aware atomic JSON storage shared by user state files."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


class RecoveringJsonFile:
    """Load validated JSON while preserving corrupt state and a known-good backup."""

    def __init__(self, path: Path, *, label: str) -> None:
        self.path = path
        self.label = label
        self.warning = ""
        self.recovery_path: Path | None = None
        self._save_error = ""

    @property
    def backup_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".bak")

    def load(self, parser: Callable[[object], T | None]) -> T | None:
        self.warning = ""
        self.recovery_path = None
        self._save_error = ""
        if not self.path.exists():
            return self._load_backup(parser, primary_problem="")
        try:
            parsed = self._read_validated(self.path, parser)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            problem = str(exc) or exc.__class__.__name__
            if not self._preserve_corrupt_file(problem):
                return self._load_backup(parser, primary_problem=problem)
            return self._load_backup(parser, primary_problem=problem)
        return parsed

    def save(self, payload: object) -> None:
        if self._save_error:
            raise OSError(self._save_error)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._restrict(temporary)
        os.replace(temporary, self.path)

        # The primary file is already saved; a failing backup copy must not make the
        # caller believe the new value was rejected.
        backup_temporary = self.backup_path.with_suffix(self.backup_path.suffix + ".tmp")
        try:
            shutil.copyfile(self.path, backup_temporary)
            self._restrict(backup_temporary)
            os.replace(backup_temporary, self.backup_path)
        except OSError:
            with contextlib.suppress(OSError):
                backup_temporary.unlink()

    def _read_validated(self, path: Path, parser: Callable[[object], T | None]) -> T:
        payload = json.loads(path.read_text(encoding="utf-8"))
        parsed = parser(payload)
        if parsed is None:
            raise ValueError(f"{self.label} has an unsupported or damaged structure.")
        return parsed

    def _load_backup(
        self,
        parser: Callable[[object], T | None],
        *,
        primary_problem: str,
    ) -> T | None:
        if not self.backup_path.is_file():
            if primary_problem and not self.warning:
                self.warning = f"{self.label} could not be read: {primary_problem}"
            return None
        try:
            parsed = self._read_validated(self.backup_path, parser)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            backup_problem = str(exc) or exc.__class__.__name__
            if primary_problem:
                self.warning = (
                    f"{self.label} and its backup could not be read. "
                    f"Primary: {primary_problem}; backup: {backup_problem}"
                )
            return None
        if primary_problem:
            suffix = (
                f" The damaged file was preserved at {self.recovery_path}."
                if self.recovery_path is not None
                else ""
            )
            self.warning = f"{self.label} was restored from its last good backup.{suffix}"
        else:
            self.warning = f"{self.label} was restored from its last good backup."
        return parsed

    def _preserve_corrupt_file(self, problem: str) -> bool:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        base = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
        recovery = base
        number = 2
        while recovery.exists():
            recovery = base.with_name(f"{base.stem}-{number}{base.suffix}")
            number += 1
        try:
            os.replace(self.path, recovery)
        except OSError as exc:
            self._save_error = (
                f"{self.label} is damaged and could not be preserved safely ({exc}). "
                "No new state will be saved over it."
            )
            self.warning = self._save_error
            return False
        self.recovery_path = recovery
        self.warning = (
            f"{self.label} was damaged ({problem}) and was preserved at {recovery}."
        )
        return True

    @staticmethod
    def _restrict(path: Path) -> None:
        if os.name != "nt":
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
