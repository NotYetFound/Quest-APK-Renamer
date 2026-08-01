"""Typed domain models shared by workflows and platform adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from quest_renamer.domain.signers import SignerIdentity


class CheckState(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BundleDraft:
    root: Path
    apk: Path
    obbs: tuple[Path, ...] = ()
    manifest: Path | None = None
    game_name: str = ""
    package_name: str = ""
    version_code: str = ""
    signer_identity: SignerIdentity | None = None

    @property
    def total_size(self) -> int:
        paths = (self.apk, *self.obbs)
        return sum(path.stat().st_size for path in paths if path.is_file())


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    key: str
    label: str
    state: CheckState
    detail: str = ""


@dataclass(frozen=True, slots=True)
class BuildRequest:
    source: BundleDraft
    package_name: str
    output_root: Path
    copy_obbs: bool = True
    sign_apk: bool = True
    patches: tuple[str, ...] = field(default_factory=tuple)
    replace_source: bool = False


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    connected: bool
    status: str = "disconnected"
    serial: str = ""
    model: str = ""
    free_bytes: int | None = None
    detail: str = ""
