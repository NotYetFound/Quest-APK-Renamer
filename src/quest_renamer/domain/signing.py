"""Signing identity state and backup workflow results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SigningState:
    exists: bool
    complete: bool
    backed_up: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SigningBackupResult:
    destination: Path


@dataclass(frozen=True, slots=True)
class SigningRestoreResult:
    source: Path
    recovery: Path | None = None


class SigningBackupError(RuntimeError):
    pass


class SigningIdentityAlreadyExists(SigningBackupError):
    pass
