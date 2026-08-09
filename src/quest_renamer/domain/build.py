"""Build results and diagnostics independent of the UI and external tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PackageRewriteReport:
    changed_files: int
    changed_occurrences: int
    preserved_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BuildResult:
    output_root: Path
    apk: Path
    obbs: tuple[Path, ...]
    manifest: Path
    report: Path
    rewrite: PackageRewriteReport
    recovery_root: Path | None = None
    text_report: Path | None = None
    signing_keystore: Path | None = None
    signing_metadata: Path | None = None
    signing_key_sha256: str = ""


class BuildError(RuntimeError):
    def __init__(self, message: str, *, partial_output: Path | None = None) -> None:
        self.partial_output = partial_output
        super().__init__(message)
