"""Replaceable boundaries between workflows and external systems."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from quest_renamer.domain.analysis import ApkAnalysis
from quest_renamer.domain.build import BuildResult
from quest_renamer.domain.inspection import DetailedApkAnalysis
from quest_renamer.domain.installation import BundleInstallResult
from quest_renamer.domain.models import BuildRequest, BundleDraft, DeviceSnapshot
from quest_renamer.domain.operations import CancellationToken
from quest_renamer.domain.preflight import PreflightResult
from quest_renamer.domain.signing import (
    SigningBackupResult,
    SigningRestoreResult,
    SigningState,
)

ProgressCallback = Callable[[float, str], None]


class BundleInspector(Protocol):
    def inspect_folder(self, folder: Path) -> BundleDraft: ...
    def inspect_apk(self, apk: Path) -> BundleDraft: ...


class BulkBundleInspector(BundleInspector, Protocol):
    pass


class ApkAnalyzer(Protocol):
    def analyze(
        self,
        apk: Path,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: Callable[[str], None] | None = None,
    ) -> ApkAnalysis: ...


class DetailedInspector(Protocol):
    def inspect(
        self,
        apk: Path,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: Callable[[str], None] | None = None,
    ) -> DetailedApkAnalysis: ...


class PreflightService(Protocol):
    def check(
        self,
        request: BuildRequest,
        *,
        device: DeviceSnapshot | None = None,
    ) -> PreflightResult: ...


class BuildEngine(Protocol):
    def build(
        self,
        request: BuildRequest,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: Callable[[str], None] | None = None,
    ) -> BuildResult: ...


class BundleInstaller(Protocol):
    def install_bundle(
        self,
        bundle: BundleDraft,
        serial: str,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: Callable[[str], None] | None = None,
        allow_existing: bool = False,
    ) -> BundleInstallResult: ...

    def retry_obbs(
        self,
        bundle: BundleDraft,
        serial: str,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: Callable[[str], None] | None = None,
    ) -> BundleInstallResult: ...


class SigningManager(Protocol):
    root: Path

    def state(self) -> SigningState: ...

    def backup_to(
        self,
        parent: Path,
        *,
        token: CancellationToken | None = None,
        log: Callable[[str], None] | None = None,
    ) -> SigningBackupResult: ...

    def restore_from(
        self,
        source: Path,
        *,
        replace_existing: bool = False,
        token: CancellationToken | None = None,
        log: Callable[[str], None] | None = None,
    ) -> SigningRestoreResult: ...


class DeviceMonitor(Protocol):
    def snapshot(self) -> DeviceSnapshot: ...


class DeviceService(DeviceMonitor, Protocol):
    def install(
        self,
        bundle: BundleDraft,
        progress: ProgressCallback,
        cancelled: Callable[[], bool],
    ) -> None: ...


class PlatformService(Protocol):
    def reveal(self, path: Path) -> None: ...

    def move_to_trash(self, path: Path) -> None: ...
