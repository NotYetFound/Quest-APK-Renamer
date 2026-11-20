"""Contract for per-game fixes applied while a build renames a package.

A game fix targets one game, identified by its SOURCE package ID, and runs only
for builds whose source package it lists. Inside a matching game an unrecognised
layout raises ``GameFixError`` instead of being skipped; a game whose target
files are simply absent is a no-op.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from quest_renamer.domain.operations import CancellationToken


class GameFixError(ValueError):
    """A game-specific fix could not be applied safely.

    Stays a ``ValueError`` so the build engine's ``except ValueError`` turns it
    into a failed build with that message. Nothing is published or replaced.
    """


@dataclass(frozen=True, slots=True)
class GameFixContext:
    old_package: str
    new_package: str
    token: CancellationToken
    log: Callable[[str], None]


@dataclass(frozen=True, slots=True)
class DecodedApkFixResult:
    """Outcome of a decoded-APK fix.

    ``rewritten_files`` are decoded-relative POSIX paths the fix rewrote, so the
    engine can drop them from the preserved-references list.
    """

    rewritten_files: tuple[str, ...]
    report: tuple[str, ...]


class GameFix(Protocol):
    fix_id: str
    title: str
    source_packages: frozenset[str]

    def apply_to_decoded_apk(
        self, context: GameFixContext, decoded: Path
    ) -> DecodedApkFixResult: ...

    def apply_to_obb(self, context: GameFixContext, obb_path: Path) -> tuple[str, ...]: ...
