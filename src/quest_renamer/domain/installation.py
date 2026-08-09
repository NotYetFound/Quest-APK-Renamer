"""Verified Quest installation results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstalledObb:
    source: Path
    remote_path: str
    size: int
    action: str = "uploaded"


@dataclass(frozen=True, slots=True)
class BundleInstallResult:
    package_name: str
    apk: Path
    obbs: tuple[InstalledObb, ...]
    package_verified: bool


class BundleInstallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failed_obbs: tuple[Path, ...] = (),
    ) -> None:
        self.failed_obbs = failed_obbs
        super().__init__(message)


class InstalledPackageConflict(BundleInstallError):
    def __init__(self, package_name: str) -> None:
        self.package_name = package_name
        super().__init__(f"{package_name} is already installed on the Quest.")
