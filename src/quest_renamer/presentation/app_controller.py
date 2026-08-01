"""Small QML-facing controller; long-running work belongs in workflow services."""

from __future__ import annotations

import datetime as dt
import platform
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from quest_renamer import __version__
from quest_renamer.domain.analysis import ApkAnalysis
from quest_renamer.domain.build import BuildError, BuildResult
from quest_renamer.domain.installation import (
    BundleInstallError,
    BundleInstallResult,
    InstalledPackageConflict,
)
from quest_renamer.domain.models import BuildRequest, BundleDraft, DeviceSnapshot
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.domain.package_ids import package_id_error, with_tag
from quest_renamer.domain.preflight import PreflightResult
from quest_renamer.domain.signing import (
    SigningBackupResult,
    SigningIdentityAlreadyExists,
    SigningRestoreResult,
)
from quest_renamer.infrastructure.activity_log import ActivityLog
from quest_renamer.infrastructure.adb_device import AdbDeviceService
from quest_renamer.infrastructure.app_paths import AppPaths, platform_app_paths
from quest_renamer.infrastructure.build_recovery import (
    clear_build_recovery,
    read_build_recovery,
)
from quest_renamer.infrastructure.desktop_open import open_local_path
from quest_renamer.infrastructure.local_bundles import (
    BundleSelectionError,
    LocalBundleInspector,
)
from quest_renamer.infrastructure.managed_outputs import (
    ManagedOutput,
    ManagedOutputError,
    inspect_managed_output,
)
from quest_renamer.infrastructure.older_firmware_patch import PATCH_ID
from quest_renamer.infrastructure.settings_store import JsonSettingsStore
from quest_renamer.services.contracts import (
    ApkAnalyzer,
    BuildEngine,
    BundleInspector,
    BundleInstaller,
    DeviceMonitor,
    PreflightService,
    SigningManager,
)
from quest_renamer.services.preflight import default_output_folder


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    result: ApkAnalysis | None = None
    error: str = ""
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class BuildOutcome:
    result: BuildResult | None = None
    error: str = ""
    partial_output: Path | None = None


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    bundle: BundleDraft
    result: BundleInstallResult | None = None
    error: str = ""
    cancelled: bool = False
    failed_obbs: tuple[Path, ...] = ()
    conflict_package: str = ""


@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    source: Path
    error: str = ""
    moved_to_trash: bool = False


@dataclass(frozen=True, slots=True)
class OldOutputCleanupOutcome:
    output: ManagedOutput
    error: str = ""


@dataclass(frozen=True, slots=True)
class SigningOperationOutcome:
    action: str
    backup: SigningBackupResult | None = None
    restore: SigningRestoreResult | None = None
    source: Path | None = None
    confirmation_required: bool = False
    error: str = ""


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1000 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1000
    return f"{value} B"


class AppController(QObject):
    bundleChanged = Signal()
    packageIdChanged = Signal()
    noticeChanged = Signal()
    readinessChanged = Signal()
    deviceChanged = Signal()
    deviceSnapshotReady = Signal(object)
    analysisProgressReady = Signal(int, float, str)
    analysisOutcomeReady = Signal(int, object)
    buildProgressReady = Signal(int, float, str)
    buildOutcomeReady = Signal(int, object)
    partialOutputChanged = Signal()
    outputChanged = Signal()
    installProgressReady = Signal(int, float, str)
    installOutcomeReady = Signal(int, object)
    sourceCleanupReady = Signal(object)
    oldOutputCleanupReady = Signal(object)
    outputCleanupConfirmationRequested = Signal(str, str, str)
    packageConflictRequested = Signal(str)
    signingBackupReminderRequested = Signal()
    signingRestoreConfirmationRequested = Signal(str)
    replaceSourceConfirmationRequested = Signal()
    signingOutcomeReady = Signal(object)
    signingChanged = Signal()
    workerLogReady = Signal(str)
    settingsChanged = Signal()
    activityChanged = Signal()

    def __init__(
        self,
        inspector: BundleInspector | None = None,
        analyzer: ApkAnalyzer | None = None,
        preflight_service: PreflightService | None = None,
        build_engine: BuildEngine | None = None,
        bundle_installer: BundleInstaller | None = None,
        signing_manager: SigningManager | None = None,
        older_firmware_asset_available: bool = False,
        device_service: DeviceMonitor | None = None,
        settings_store: JsonSettingsStore | None = None,
        activity_log: ActivityLog | None = None,
        paths: AppPaths | None = None,
        move_to_trash: Callable[[Path], None] | None = None,
        path_opener: Callable[[Path], bool] | None = None,
        support_tool_summary: str = "Not reported",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths or platform_app_paths()
        self._inspector = inspector or LocalBundleInspector()
        self._analyzer = analyzer
        self._preflight_service = preflight_service
        self._build_engine = build_engine
        self._bundle_installer = bundle_installer
        self._signing_manager = signing_manager
        self._older_firmware_asset_available = older_firmware_asset_available
        self._device_service = device_service or AdbDeviceService()
        self._settings_store = settings_store or JsonSettingsStore(self._paths.settings_file)
        self._activity_log = activity_log or ActivityLog(self._paths.log_file)
        self._move_to_trash = move_to_trash
        self._path_opener = path_opener or open_local_path
        self._support_tool_summary = support_tool_summary
        self._external_busy_provider: Callable[[], bool] = lambda: False
        self._settings = self._settings_store.load()
        self._bundle: BundleDraft | None = None
        self._package_id = ""
        self._analysis_state = "idle"
        self._analysis_progress = 0.0
        self._analysis_message = ""
        self._analysis_token: CancellationToken | None = None
        self._analysis_generation = 0
        self._analysis_started_at = 0.0
        self._analysis_log_step = ""
        self._preflight: PreflightResult | None = None
        self._build_state = "idle"
        self._build_progress = 0.0
        self._build_message = ""
        self._build_token: CancellationToken | None = None
        self._build_generation = 0
        self._build_started_at = 0.0
        self._build_log_step = ""
        self._build_result: BuildResult | None = None
        recovery = read_build_recovery(self._paths.build_recovery_file)
        self._partial_output: Path | None = recovery.staging if recovery else None
        self._last_failure_report: Path | None = None
        self._output_parent: Path | None = None
        self._older_firmware_supported = False
        self._install_state = "idle"
        self._install_progress = 0.0
        self._install_message = ""
        self._install_token: CancellationToken | None = None
        self._install_generation = 0
        self._install_started_at = 0.0
        self._install_log_step = ""
        self._retry_bundle: BundleDraft | None = None
        self._pending_conflict_bundle: BundleDraft | None = None
        self._pending_restore: Path | None = None
        self._pending_old_output: ManagedOutput | None = None
        self._old_output_cleanup_busy = False
        self._signing_busy = False
        self._notice = "Choose a game folder to begin."
        self._notice_tone = "neutral"
        self._device = DeviceSnapshot(
            False,
            status="checking",
            detail="Looking for a connected headset.",
        )
        self._device_check_running = False
        self._activity: deque[str] = deque(self._activity_log.tail(), maxlen=400)
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(12_000)
        self._device_timer.timeout.connect(self.refreshDevice)
        self.deviceSnapshotReady.connect(self._apply_device_snapshot)
        self.analysisProgressReady.connect(self._apply_analysis_progress)
        self.analysisOutcomeReady.connect(self._apply_analysis_outcome)
        self.buildProgressReady.connect(self._apply_build_progress)
        self.buildOutcomeReady.connect(self._apply_build_outcome)
        self.installProgressReady.connect(self._apply_install_progress)
        self.installOutcomeReady.connect(self._apply_install_outcome)
        self.sourceCleanupReady.connect(self._apply_source_cleanup)
        self.oldOutputCleanupReady.connect(self._apply_old_output_cleanup)
        self.signingOutcomeReady.connect(self._apply_signing_outcome)
        self.workerLogReady.connect(self._record_activity)
        self._record_event(
            "APP",
            "Session started",
            (
                ("Version", __version__),
                ("System", f"{platform.system()} {platform.release()} ({platform.machine()})"),
                ("Data folder", str(self._paths.data)),
                ("Log file", str(self._paths.log_file)),
            ),
        )

    @Property(bool, notify=readinessChanged)
    def canBuild(self) -> bool:
        return self._can_build()

    def _can_build(self) -> bool:
        if (
            self._build_state == "running"
            or self._install_state == "running"
            or self._signing_busy
            or self._external_busy_provider()
            or self._build_engine is None
        ):
            return False
        if self._bundle is None or self._package_error():
            return False
        if self._analyzer is not None and self._analysis_state != "ready":
            return False
        return self._preflight is None or self._preflight.ready

    @Property(bool, notify=readinessChanged)
    def isBuilding(self) -> bool:
        return self._build_state == "running"

    @Property(bool, notify=readinessChanged)
    def isBusy(self) -> bool:
        return self.has_active_work() or self._external_busy_provider()

    def has_active_work(self) -> bool:
        return (
            self._analysis_state == "running"
            or self._build_state == "running"
            or self._install_state == "running"
            or self._signing_busy
            or self._old_output_cleanup_busy
        )

    def current_device(self) -> DeviceSnapshot:
        return self._device

    def set_external_busy_provider(self, provider: Callable[[], bool]) -> None:
        self._external_busy_provider = provider

    def set_older_firmware_asset_available(self, available: bool) -> None:
        if available == self._older_firmware_asset_available:
            return
        self._older_firmware_asset_available = available
        if not available and self._settings.older_firmware_patch:
            self._settings = self._settings.with_value("older_firmware_patch", False)
            with suppress(OSError):
                self._settings_store.save(self._settings)
        self.settingsChanged.emit()
        self.readinessChanged.emit()

    @Slot()
    def refreshExternalBusy(self) -> None:
        self.readinessChanged.emit()

    @Slot()
    def refreshToolchainState(self) -> None:
        """Re-run readiness after repaired tool adapters have been activated."""
        self._preflight = None
        self._refresh_preflight()
        self.readinessChanged.emit()

    @Property(bool, notify=readinessChanged)
    def isInstalling(self) -> bool:
        return self._install_state == "running"

    @Property(float, notify=readinessChanged)
    def installProgress(self) -> float:
        return self._install_progress

    @Property(str, notify=readinessChanged)
    def installLabel(self) -> str:
        return self._install_message or "Installing APK"

    @Property(str, notify=readinessChanged)
    def installActionLabel(self) -> str:
        return "Installing…" if self._install_state == "running" else "Install finished folder…"

    @Property(bool, notify=readinessChanged)
    def canInstallBuilt(self) -> bool:
        return (
            self._build_result is not None
            and not self.isBusy
            and self._device.connected
            and bool(self._device.serial)
            and self._bundle_installer is not None
        )

    @Property(bool, notify=readinessChanged)
    def canInstallFolder(self) -> bool:
        return (
            not self.isBusy
            and self._device.connected
            and bool(self._device.serial)
            and self._bundle_installer is not None
        )

    @Property(bool, notify=readinessChanged)
    def canRetryObbs(self) -> bool:
        return self._retry_bundle is not None and not self.isBusy

    @Property(str, notify=signingChanged)
    def signingStatus(self) -> str:
        if self._signing_busy:
            return "Working with the signing identity…"
        if self._signing_manager is None:
            return "Signing-key management is unavailable"
        return self._signing_manager.state().detail

    @Property(bool, notify=readinessChanged)
    def canBackupSigningKey(self) -> bool:
        return (
            self._signing_manager is not None
            and self._signing_manager.state().complete
            and not self.isBusy
        )

    @Property(bool, notify=readinessChanged)
    def canRestoreSigningKey(self) -> bool:
        return self._signing_manager is not None and not self.isBusy

    @Property(float, notify=readinessChanged)
    def buildProgress(self) -> float:
        return self._build_progress

    @Property(str, notify=readinessChanged)
    def buildLabel(self) -> str:
        if self._build_message:
            return self._build_message
        if self._patch_only_build():
            return "Applying older-firmware patch"
        if self._settings.replace_source_after_build:
            return "Building verified replacement"
        return "Building renamed copy"

    @Property(str, notify=readinessChanged)
    def buildActionLabel(self) -> str:
        if self._build_state == "running":
            return "Cancel safely"
        if self._build_result is not None:
            return "Open finished folder"
        if self._patch_only_build():
            return (
                "Apply patch and replace source"
                if self._settings.replace_source_after_build
                else "Apply firmware patch"
            )
        if self._settings.replace_source_after_build:
            return "Build and replace source"
        return "Build renamed copy"

    @Property(str, notify=partialOutputChanged)
    def partialOutputFolder(self) -> str:
        return str(self._partial_output) if self._partial_output else ""

    @Property(bool, notify=readinessChanged)
    def isAnalyzing(self) -> bool:
        return self._analysis_state == "running"

    @Property(float, notify=readinessChanged)
    def analysisProgress(self) -> float:
        return self._analysis_progress

    @Property(str, notify=readinessChanged)
    def analysisLabel(self) -> str:
        if self._analysis_state == "running":
            return self._analysis_message or "Reading APK"
        if self._analysis_state == "ready":
            return "APK checked"
        if self._analysis_state == "error":
            return "APK check failed"
        return "Waiting for a game"

    @Property(bool, notify=bundleChanged)
    def hasBundle(self) -> bool:
        return self._bundle is not None

    @Property(str, notify=bundleChanged)
    def folderName(self) -> str:
        return self._bundle.root.name if self._bundle else ""

    @Property(str, notify=bundleChanged)
    def folderPath(self) -> str:
        return str(self._bundle.root) if self._bundle else ""

    @Property(str, notify=bundleChanged)
    def apkPath(self) -> str:
        return str(self._bundle.apk) if self._bundle else ""

    @Property(str, notify=bundleChanged)
    def apkName(self) -> str:
        return self._bundle.apk.name if self._bundle else ""

    @Property(str, notify=bundleChanged)
    def bundleSize(self) -> str:
        return _format_bytes(self._bundle.total_size) if self._bundle else ""

    @Property(str, notify=bundleChanged)
    def obbSummary(self) -> str:
        if not self._bundle:
            return ""
        count = len(self._bundle.obbs)
        return "No OBB files" if not count else f"{count} OBB file{'s' if count != 1 else ''}"

    @Property(str, notify=bundleChanged)
    def sourcePackage(self) -> str:
        if not self._bundle:
            return ""
        return self._bundle.package_name or "Will be read from the APK during analysis"

    @Property(str, notify=bundleChanged)
    def versionSummary(self) -> str:
        if not self._bundle or not self._bundle.version_code:
            return ""
        return f"Version {self._bundle.version_code}"

    @Property(str, notify=bundleChanged)
    def signerLineage(self) -> str:
        if not self._bundle:
            return "Signer appears after APK analysis"
        identity = self._bundle.signer_identity
        signer = identity.full_name if identity is not None else "Unrecognized signer"
        if self._bundle.signer_lineage:
            return f"Current: {signer}  •  {self._bundle.signer_lineage}"
        return f"Current: {signer}"

    @Property(str, notify=outputChanged)
    def outputFolder(self) -> str:
        output = self._output_folder()
        return str(output) if output is not None else ""

    def _output_folder(self) -> Path | None:
        if not self._bundle:
            return None
        if self._settings.replace_source_after_build:
            return self._bundle.root
        name = default_output_folder(self._bundle.root).name
        parent = self._output_parent or self._bundle.root.parent
        return parent / name

    @Property(bool, notify=readinessChanged)
    def olderFirmwareAvailable(self) -> bool:
        return self._older_firmware_available()

    def _older_firmware_available(self) -> bool:
        return self._older_firmware_supported and self._older_firmware_asset_available

    @Property(str, notify=readinessChanged)
    def olderFirmwareDetail(self) -> str:
        return self._older_firmware_detail()

    def _older_firmware_detail(self) -> str:
        if self._older_firmware_available():
            return "Replace the existing Oculus loader for older Quest firmware"
        if self._analysis_state == "running":
            return "Compatibility is checked automatically"
        if not self._older_firmware_supported:
            return "This APK does not contain the compatible ARM64 loader"
        return "The verified compatibility asset is not installed"

    @Property(str, notify=packageIdChanged)
    def packageId(self) -> str:
        return self._package_id

    @Slot(str)
    def setPackageId(self, value: str) -> None:
        if self._build_state == "running":
            return
        value = value.strip()
        if value == self._package_id:
            return
        self._package_id = value
        self.packageIdChanged.emit()
        self._refresh_preflight()

    @Property(str, notify=packageIdChanged)
    def packageError(self) -> str:
        return self._package_error()

    def _package_error(self) -> str:
        return package_id_error(
            self._package_id,
            self._bundle.package_name if self._bundle else "",
            allow_same=self._patch_only_build(),
        )

    def _patch_only_build(self) -> bool:
        return bool(
            self._bundle
            and self._settings.older_firmware_patch
            and self._package_id == self._bundle.package_name
        )

    @Property(str, notify=noticeChanged)
    def notice(self) -> str:
        return self._notice

    @Property(str, notify=noticeChanged)
    def noticeTone(self) -> str:
        return self._notice_tone

    def _set_notice(self, message: str, tone: str = "neutral") -> None:
        self._notice = message
        self._notice_tone = tone
        self.noticeChanged.emit()

    @Property(str, notify=deviceChanged)
    def deviceTitle(self) -> str:
        return self._device_title()

    def _device_title(self) -> str:
        titles = {
            "checking": "Checking for Quest",
            "connected": self._device.model or "Quest connected",
            "tools_missing": "ADB not available",
            "permission": "USB permission needed",
            "unauthorized": "Approve USB debugging",
            "multiple": "Multiple devices found",
            "offline": "Quest is offline",
            "error": "Device check failed",
            "disconnected": "Quest not connected",
        }
        return titles.get(self._device.status, "Quest not connected")

    @Property(str, notify=deviceChanged)
    def deviceLabel(self) -> str:
        title = self._device_title()
        if self._device.connected and self._device.free_bytes is not None:
            return f"{title}  •  {_format_bytes(self._device.free_bytes)} free"
        return title

    @Property(str, notify=deviceChanged)
    def deviceDetail(self) -> str:
        return self._device.detail

    @Property(str, notify=deviceChanged)
    def deviceTone(self) -> str:
        if self._device.status == "connected":
            return "success"
        if self._device.status in {"permission", "unauthorized", "multiple", "offline"}:
            return "warning"
        if self._device.status == "error":
            return "error"
        return "neutral"

    @Property(dict, notify=settingsChanged)
    def settings(self) -> dict[str, bool | str]:
        return {
            "copyObbs": self._settings.copy_obbs,
            "signApks": self._settings.sign_apks,
            "olderFirmwarePatch": self._settings.older_firmware_patch,
            "deleteSourceAfterInstall": self._settings.delete_source_after_install,
            "replaceSourceAfterBuild": self._settings.replace_source_after_build,
            "automaticPreflight": self._settings.automatic_preflight,
            "checkUpdates": self._settings.check_updates,
            "keyBackupReminder": self._settings.key_backup_reminder,
            "dismissedUpdate": self._settings.dismissed_update,
        }

    def update_preferences(self) -> tuple[bool, str]:
        return self._settings.check_updates, self._settings.dismissed_update

    def dismiss_update_version(self, version: str) -> None:
        updated = self._settings.with_value("dismissed_update", version)
        try:
            self._settings_store.save(updated)
        except OSError as exc:
            self._record_activity(f"Update dismissal could not be saved: {exc}")
            return
        self._settings = updated
        self.settingsChanged.emit()

    @Property(str, notify=activityChanged)
    def activityText(self) -> str:
        return "\n".join(self._activity)

    @Property(str, notify=activityChanged)
    def activityDisplayText(self) -> str:
        lines = tuple(self._activity)
        latest_session = next(
            (
                index
                for index in range(len(lines) - 1, -1, -1)
                if "[APP] Session started" in lines[index]
            ),
            0,
        )
        visible = lines[latest_session:]
        if latest_session > 0:
            visible = ("Earlier sessions remain in the saved log.", "", *visible)
        return "\n".join(visible)

    @Property(str, notify=activityChanged)
    def supportInformation(self) -> str:
        return self._support_information()

    def _support_information(self) -> str:
        bundle = self._bundle
        recent = self._activity_log.tail()[-80:]
        return "\n".join(
            [
                "QUEST APK RENAMER — SUPPORT INFORMATION",
                f"App version: {__version__}",
                f"System: {platform.platform()}",
                f"Python: {platform.python_version()}",
                f"PySide: {pyside_version}",
                f"Device: {self._device_title()} — {self._device.detail}",
                f"Tools: {self._support_tool_summary}",
                f"Selected folder: {bundle.root if bundle else 'None'}",
                f"Package: {bundle.package_name if bundle else 'None'}",
                f"Requested package: {self._package_id or 'None'}",
                f"Build state: {self._build_state}",
                f"Install state: {self._install_state}",
                f"Log file: {self._paths.log_file}",
                "",
                "RECENT LOG",
                "----------",
                *(recent or ("No log entries.",)),
            ]
        )

    @Slot(str)
    def setSupportToolSummary(self, summary: str) -> None:
        self._support_tool_summary = summary

    @Slot()
    def copySupportInformation(self) -> None:
        if QGuiApplication.instance() is None:
            self._set_notice("The clipboard is unavailable in this session.", "warning")
            return
        QGuiApplication.clipboard().setText(self._support_information())
        self._set_notice(
            "Support information copied. Review local paths before sharing it.",
            "success",
        )
        self._record_event("SUPPORT", "Support information copied to the clipboard")

    def _record_activity(self, message: str) -> None:
        prefixes = {
            "Build": "BUILD",
            "Install": "INSTALL",
            "APK analysis": "ANALYSIS",
            "Signing": "SIGNING",
        }
        prefix, separator, detail = message.partition(": ")
        if separator and prefix in prefixes:
            self._record_event(prefixes[prefix], detail)
            return
        self._activity.append(self._activity_log.append(message))
        self.activityChanged.emit()

    def _record_event(
        self,
        category: str,
        title: str,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._activity.extend(self._activity_log.append_event(category, title, details))
        self.activityChanged.emit()

    @staticmethod
    def _elapsed(started_at: float) -> str:
        elapsed = max(0.0, time.monotonic() - started_at)
        if elapsed < 60:
            return f"{elapsed:.1f} seconds"
        minutes, seconds = divmod(int(elapsed), 60)
        return f"{minutes} min {seconds} sec"

    @Slot(str)
    def recordActivity(self, message: str) -> None:
        self._record_activity(message)

    @Slot()
    def startDeviceMonitoring(self) -> None:
        self.refreshDevice()
        self._device_timer.start()

    @Slot()
    def refreshDevice(self) -> None:
        if self._device_check_running:
            return
        self._device_check_running = True
        threading.Thread(target=self._device_worker, daemon=True).start()

    def _device_worker(self) -> None:
        snapshot = self._device_service.snapshot()
        self.deviceSnapshotReady.emit(snapshot)

    @Slot(object)
    def _apply_device_snapshot(self, snapshot: object) -> None:
        self._device_check_running = False
        if not isinstance(snapshot, DeviceSnapshot):
            return
        previous = (self._device.status, self._device.serial, self._device.free_bytes)
        current = (snapshot.status, snapshot.serial, snapshot.free_bytes)
        self._device = snapshot
        self.deviceChanged.emit()
        self._refresh_preflight()
        if current != previous:
            self._record_activity(f"Device: {self._device_title()}. {snapshot.detail}")

    @Slot(str, bool)
    def setSetting(self, name: str, value: bool) -> None:
        if name == "replace_source_after_build":
            self.requestReplaceSource(value)
            return
        if name == "older_firmware_patch" and value and not self._older_firmware_available():
            self._set_notice(self._older_firmware_detail(), "warning")
            return
        try:
            updated = self._settings.with_value(name, value)
        except (KeyError, TypeError):
            self._record_activity(f"Ignored unknown setting: {name}")
            return
        if updated == self._settings:
            return
        try:
            self._settings_store.save(updated)
        except OSError as exc:
            self._set_notice(f"Settings could not be saved: {exc}", "error")
            self._record_activity(f"Settings save failed: {exc}")
            return
        self._settings = updated
        self.settingsChanged.emit()
        self._refresh_preflight()
        self._record_activity(f"Setting changed: {name} = {value}")

    @Slot(bool)
    def requestReplaceSource(self, value: bool) -> None:
        if self.isBusy:
            self.settingsChanged.emit()
            return
        if value == self._settings.replace_source_after_build:
            self.settingsChanged.emit()
            return
        if value:
            self.replaceSourceConfirmationRequested.emit()
            return
        self._set_replace_source(False)

    @Slot()
    def confirmReplaceSource(self) -> None:
        self._set_replace_source(True)

    @Slot()
    def cancelReplaceSource(self) -> None:
        self.settingsChanged.emit()

    def _set_replace_source(self, enabled: bool) -> None:
        updated = self._settings.with_value("replace_source_after_build", enabled)
        if enabled:
            # A replacement must carry every expansion file forward.
            updated = updated.with_value("copy_obbs", True)
        try:
            self._settings_store.save(updated)
        except OSError as exc:
            self._set_notice(f"Settings could not be saved: {exc}", "error")
            self._record_activity(f"Settings save failed: {exc}")
            self.settingsChanged.emit()
            return
        self._settings = updated
        self._build_result = None
        self._build_state = "idle"
        self._build_progress = 0.0
        self.settingsChanged.emit()
        self.outputChanged.emit()
        self.readinessChanged.emit()
        self._refresh_preflight()
        mode = "replace source" if enabled else "create a separate folder"
        self._set_notice(f"Output mode set to {mode}.")
        self._record_activity(f"Output mode changed: {mode}.")

    @Slot()
    def clearActivity(self) -> None:
        self._activity.clear()
        self._activity_log.clear()
        self._record_activity("Activity view cleared.")

    @Slot()
    def openDataFolder(self) -> None:
        self._paths.data.mkdir(parents=True, exist_ok=True)
        self._open_local_path(self._paths.data, "app data folder")

    def _open_local_path(self, path: Path, label: str) -> bool:
        if not path.exists():
            self._set_notice(f"The {label} no longer exists.", "warning")
            return False
        if self._path_opener(path):
            return True
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            return True
        self._set_notice(f"No application is available to open the {label}.", "warning")
        self._record_activity(f"Could not open {label}: {path}")
        return False

    @Property(str, constant=True)
    def logPath(self) -> str:
        return str(self._paths.log_file)

    @Property(str, constant=True)
    def logExportFileName(self) -> str:
        return f"Quest-APK-Renamer-{dt.datetime.now():%Y%m%d-%H%M%S}.log"

    @Slot()
    def openLogFile(self) -> None:
        try:
            self._paths.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._paths.log_file.touch(exist_ok=True)
        except OSError as exc:
            self._set_notice(f"The log file could not be opened: {exc}", "error")
            return
        self._open_local_path(self._paths.log_file, "saved log file")

    @Property(bool, notify=readinessChanged)
    def hasFailureReport(self) -> bool:
        return self._last_failure_report is not None and self._last_failure_report.is_file()

    @Slot()
    def openFailureReport(self) -> None:
        report = self._last_failure_report
        if report is None or not report.is_file():
            self._set_notice("No build report is available for this failure.", "warning")
            return
        self._open_local_path(report, "build report")

    @staticmethod
    def _report_in(folder: Path) -> Path | None:
        for name in ("RENAME-REPORT.txt", "quest-renamer-report.txt"):
            candidate = folder / name
            if candidate.is_file():
                return candidate
        return None

    @Slot(QUrl)
    def exportLog(self, url: QUrl) -> None:
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if not local:
            return
        destination = Path(local).expanduser()
        try:
            self._activity_log.export(destination)
        except OSError as exc:
            self._set_notice(f"The log copy could not be saved: {exc}", "error")
            self._record_event("LOG", "Export failed", (("Reason", str(exc)),))
            return
        self._record_event("LOG", "Readable log exported", (("Saved to", str(destination)),))
        self._set_notice(f"Log saved as {destination.name}.", "success")

    @Slot(QUrl)
    def requestOldOutputCleanup(self, url: QUrl) -> None:
        if self.isBusy:
            return
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if not local:
            return
        try:
            output = inspect_managed_output(Path(local))
        except (ManagedOutputError, OSError) as exc:
            self._set_notice(str(exc), "error")
            self._record_event(
                "CLEANUP",
                "Old-output safety check rejected a folder",
                (("Folder", local), ("Reason", str(exc))),
            )
            return
        self._pending_old_output = output
        self.outputCleanupConfirmationRequested.emit(
            str(output.root),
            _format_bytes(output.total_size),
            output.package_name,
        )

    @Slot()
    def confirmOldOutputCleanup(self) -> None:
        output = self._pending_old_output
        self._pending_old_output = None
        if output is None or self.has_active_work():
            return
        self._old_output_cleanup_busy = True
        self._set_notice("Moving the verified old output to Trash…")
        self.readinessChanged.emit()
        self._record_event(
            "CLEANUP",
            "Moving an old app-created output to Trash",
            (
                ("Folder", str(output.root)),
                ("Package", output.package_name),
                ("Files", str(output.file_count)),
                ("Size", _format_bytes(output.total_size)),
            ),
        )
        threading.Thread(
            target=self._old_output_cleanup_worker,
            args=(output,),
            daemon=True,
        ).start()

    @Slot()
    def cancelOldOutputCleanup(self) -> None:
        self._pending_old_output = None

    def _old_output_cleanup_worker(self, output: ManagedOutput) -> None:
        try:
            if self._move_to_trash is None:
                raise OSError("Desktop Trash integration is unavailable on this system.")
            self._move_to_trash(output.root)
            outcome = OldOutputCleanupOutcome(output)
        except Exception as exc:  # platform Trash adapters may use different errors
            outcome = OldOutputCleanupOutcome(output, error=str(exc))
        self.oldOutputCleanupReady.emit(outcome)

    @Slot(object)
    def _apply_old_output_cleanup(self, raw_outcome: object) -> None:
        if not isinstance(raw_outcome, OldOutputCleanupOutcome):
            return
        self._old_output_cleanup_busy = False
        output = raw_outcome.output
        if raw_outcome.error:
            self._set_notice(
                f"The old output could not be moved to Trash: {raw_outcome.error}", "error"
            )
            self._record_event(
                "CLEANUP",
                "Old-output cleanup failed",
                (("Folder", str(output.root)), ("Reason", raw_outcome.error)),
            )
            self.readinessChanged.emit()
            return
        if self._build_result is not None and (
            self._build_result.output_root.resolve() == output.root
        ):
            self._build_result = None
            self._build_state = "idle"
            self._build_progress = 0.0
        if self._bundle is not None and self._bundle.root.resolve() == output.root:
            self._bundle = None
            self._package_id = ""
            self._analysis_state = "idle"
            self._preflight = None
            self.bundleChanged.emit()
            self.packageIdChanged.emit()
            self.outputChanged.emit()
        self._set_notice("Old output moved to Trash. It can be restored from there.", "success")
        self._record_event(
            "CLEANUP",
            "Old output moved to Trash",
            (("Folder", str(output.root)), ("Size", _format_bytes(output.total_size))),
        )
        self.readinessChanged.emit()

    @Slot(str)
    def chooseFolderPath(self, value: str) -> None:
        value = value.strip()
        if value:
            self.chooseFolder(QUrl.fromLocalFile(value))

    @Slot(QUrl)
    def chooseOutputParent(self, url: QUrl) -> None:
        if self._bundle is None or self._build_state == "running":
            return
        if self._settings.replace_source_after_build:
            self._set_notice(
                "Turn off source replacement to choose a separate save location.",
                "warning",
            )
            return
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if not local:
            return
        parent = Path(local).expanduser().resolve()
        if not parent.is_dir():
            self._set_notice("Choose an existing folder to save the renamed copy in.", "error")
            return
        self._output_parent = parent
        self._build_result = None
        self._build_state = "idle"
        self.outputChanged.emit()
        self.readinessChanged.emit()
        self._refresh_preflight()
        self._record_activity(f"Output location changed: {parent}")

    @Slot(QUrl)
    def chooseFolder(self, url: QUrl) -> None:
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if not local:
            return
        source = Path(local)
        try:
            bundle = (
                self._inspector.inspect_apk(source)
                if source.is_file() and source.suffix.lower() == ".apk"
                else self._inspector.inspect_folder(source)
            )
        except BundleSelectionError as exc:
            self._set_notice(str(exc), "error")
            self._record_activity(f"Source rejected: {exc}")
            return
        except OSError as exc:
            self._set_notice(f"The source could not be read: {exc}", "error")
            self._record_activity(f"Source could not be read: {exc}")
            return

        self._bundle = bundle
        self._preflight = None
        self._build_result = None
        self._build_state = "idle"
        self._output_parent = bundle.root.parent
        self._older_firmware_supported = False
        if self._settings.older_firmware_patch:
            self._settings = self._settings.with_value("older_firmware_patch", False)
            with suppress(OSError):
                self._settings_store.save(self._settings)
            self.settingsChanged.emit()
        if bundle.package_name:
            try:
                self._package_id = with_tag(bundle.package_name, "dev")
            except ValueError:
                self._package_id = ""
        else:
            self._package_id = ""
        self.bundleChanged.emit()
        self.outputChanged.emit()
        self.packageIdChanged.emit()
        self.readinessChanged.emit()
        self._record_event(
            "SOURCE",
            "Game bundle selected",
            (
                ("Folder", str(bundle.root)),
                ("APK", bundle.apk.name),
                ("Expansion files", str(len(bundle.obbs))),
                ("Total size", _format_bytes(bundle.total_size)),
                ("Detected package", bundle.package_name or "Waiting for APK analysis"),
            ),
        )
        if self._analyzer is None:
            self._analysis_state = "ready"
            self._refresh_preflight()
            self._set_notice("Bundle found. Nothing has been changed.", "success")
        else:
            self._begin_analysis(bundle)

    def _begin_analysis(self, bundle: BundleDraft) -> None:
        if self._analysis_token is not None:
            self._analysis_token.cancel()
        self._analysis_generation += 1
        generation = self._analysis_generation
        token = CancellationToken()
        self._analysis_token = token
        self._analysis_started_at = time.monotonic()
        self._analysis_log_step = "Reading APK"
        self._analysis_state = "running"
        self._analysis_progress = 0.0
        self._analysis_message = "Reading APK"
        self._last_failure_report = None
        self._set_notice("Checking the APK and preparing a safe build…")
        self._record_event("ANALYSIS", "APK analysis started", (("APK", str(bundle.apk)),))
        self.readinessChanged.emit()
        threading.Thread(
            target=self._analysis_worker,
            args=(generation, bundle.apk, token),
            daemon=True,
        ).start()

    def _analysis_worker(self, generation: int, apk: Path, token: CancellationToken) -> None:
        assert self._analyzer is not None
        try:
            result = self._analyzer.analyze(
                apk,
                token=token,
                progress=lambda value, message: self.analysisProgressReady.emit(
                    generation, value, message
                ),
                log=lambda message: self.workerLogReady.emit(f"APK analysis: {message}"),
            )
            outcome = AnalysisOutcome(result=result)
        except OperationCancelled:
            outcome = AnalysisOutcome(cancelled=True)
        except Exception as exc:  # adapter failures become a controlled UI result
            outcome = AnalysisOutcome(error=str(exc))
        self.analysisOutcomeReady.emit(generation, outcome)

    @Slot(int, float, str)
    def _apply_analysis_progress(self, generation: int, value: float, message: str) -> None:
        if generation != self._analysis_generation:
            return
        self._analysis_progress = min(1.0, max(0.0, value))
        self._analysis_message = message
        if message != self._analysis_log_step:
            self._analysis_log_step = message
            self._record_event(
                "ANALYSIS",
                message,
                (("Progress", f"{round(self._analysis_progress * 100)}%"),),
            )
        self.readinessChanged.emit()

    @Slot(int, object)
    def _apply_analysis_outcome(self, generation: int, raw_outcome: object) -> None:
        if generation != self._analysis_generation or not isinstance(
            raw_outcome, AnalysisOutcome
        ):
            return
        self._analysis_token = None
        if raw_outcome.cancelled:
            return
        if raw_outcome.result is None:
            self._analysis_state = "error"
            self._analysis_progress = 0.0
            detail = raw_outcome.error or "The APK could not be analyzed."
            self._set_notice(detail, "error")
            self._record_event(
                "ANALYSIS",
                "APK analysis failed",
                (("After", self._elapsed(self._analysis_started_at)), ("Reason", detail)),
            )
            self.readinessChanged.emit()
            return
        if self._bundle is None or self._bundle.apk != raw_outcome.result.apk:
            return

        result = raw_outcome.result
        self._older_firmware_supported = result.has_legacy_loader
        self._bundle = replace(
            self._bundle,
            package_name=result.package_name,
            version_code=result.version_code,
            game_name=self._bundle.game_name or result.app_label,
            signer_identity=result.signer_identity,
            signer_lineage=result.signer_lineage,
        )
        try:
            self._package_id = with_tag(result.package_name, "dev")
        except ValueError:
            self._package_id = ""
        self._analysis_state = "ready"
        self._analysis_progress = 1.0
        self._analysis_message = "APK checked"
        self.bundleChanged.emit()
        self.packageIdChanged.emit()
        self._record_event(
            "ANALYSIS",
            "APK analysis complete",
            (
                ("Duration", self._elapsed(self._analysis_started_at)),
                ("Package", result.package_name),
                ("Version code", result.version_code or "Not reported"),
                ("CPU architectures", ", ".join(result.abis) or "None detected"),
                (
                    "Source signer",
                    result.signer_identity.full_name
                    if result.signer_identity is not None
                    else "Unrecognized or unavailable",
                ),
                ("SHA-256", result.sha256),
                (
                    "Older-firmware patch",
                    "Available for this APK" if result.has_legacy_loader else "Not applicable",
                ),
            ),
        )
        self._refresh_preflight()

    def _build_request(self) -> BuildRequest | None:
        output = self._output_folder()
        if self._bundle is None or output is None:
            return None
        return BuildRequest(
            source=self._bundle,
            package_name=self._package_id,
            output_root=output,
            copy_obbs=self._settings.copy_obbs,
            sign_apk=self._settings.sign_apks,
            patches=(PATCH_ID,) if self._settings.older_firmware_patch else (),
            replace_source=self._settings.replace_source_after_build,
        )

    @Slot()
    def installBuiltFolder(self) -> None:
        if self._build_result is None:
            self._set_notice("Build a renamed copy before installing it.", "warning")
            return
        result = self._build_result
        bundle = BundleDraft(
            root=result.output_root,
            apk=result.apk,
            obbs=result.obbs,
            manifest=result.manifest,
            game_name=self._bundle.game_name if self._bundle else result.output_root.name,
            package_name=self._package_id,
            version_code=self._bundle.version_code if self._bundle else "",
        )
        self._start_bundle_install(bundle)

    @Slot(QUrl)
    def installFinishedFolder(self, url: QUrl) -> None:
        if self._install_state == "running":
            return
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if not local:
            return
        try:
            bundle = self._inspector.inspect_folder(Path(local))
        except (BundleSelectionError, OSError) as exc:
            self._set_notice(f"That finished folder cannot be installed: {exc}", "error")
            self._record_activity(f"Install folder rejected: {exc}")
            return
        self._start_bundle_install(bundle)

    def _start_bundle_install(
        self,
        bundle: BundleDraft,
        *,
        retry_only: bool = False,
        allow_existing: bool = False,
    ) -> None:
        if self._install_state == "running":
            return
        if self._bundle_installer is None:
            self._set_notice(
                "Finished-folder installation is unavailable in this build.", "error"
            )
            return
        if not bundle.package_name:
            self._set_notice(
                "The finished folder needs a release.manifest with its package ID.",
                "error",
            )
            return
        if not self._device.connected or not self._device.serial:
            self._set_notice("Connect and authorize one Quest before installing.", "warning")
            return
        if self._device.free_bytes is not None and bundle.total_size > self._device.free_bytes:
            self._set_notice(
                f"This game needs {_format_bytes(bundle.total_size)}, but the Quest only has "
                f"{_format_bytes(self._device.free_bytes)} free.",
                "error",
            )
            return
        self._install_generation += 1
        generation = self._install_generation
        token = CancellationToken()
        self._install_token = token
        self._install_started_at = time.monotonic()
        self._install_state = "running"
        self._install_progress = 0.0
        self._last_failure_report = None
        action = "Retrying" if retry_only else "Installing"
        self._install_message = f"{action} {bundle.game_name or bundle.root.name}"
        self._install_log_step = self._install_message
        if retry_only:
            self._set_notice(
                f"Retrying {len(bundle.obbs)} failed OBB file"
                f"{'s' if len(bundle.obbs) != 1 else ''}…"
            )
        else:
            self._set_notice(
                f"Installing the APK and {len(bundle.obbs)} OBB file"
                f"{'s' if len(bundle.obbs) != 1 else ''} on "
                f"{self._device.model or 'Quest'}…"
            )
        self._record_event(
            "INSTALL",
            "OBB retry started" if retry_only else "Bundle install started",
            (
                ("Folder", str(bundle.root)),
                ("Package", bundle.package_name),
                ("APK", bundle.apk.name),
                ("OBB files", str(len(bundle.obbs))),
                ("Total size", _format_bytes(bundle.total_size)),
                ("Quest", self._device.model or self._device.serial or "Connected Quest"),
            ),
        )
        self.readinessChanged.emit()
        threading.Thread(
            target=self._install_worker,
            args=(
                generation,
                bundle,
                self._device.serial,
                token,
                retry_only,
                allow_existing,
            ),
            daemon=True,
        ).start()

    def _install_worker(
        self,
        generation: int,
        bundle: BundleDraft,
        serial: str,
        token: CancellationToken,
        retry_only: bool,
        allow_existing: bool,
    ) -> None:
        assert self._bundle_installer is not None
        try:

            def progress(value: float, message: str) -> None:
                self.installProgressReady.emit(generation, value, message)

            def log(message: str) -> None:
                self.workerLogReady.emit(f"Install: {message}")

            if retry_only:
                result = self._bundle_installer.retry_obbs(
                    bundle,
                    serial,
                    token=token,
                    progress=progress,
                    log=log,
                )
            else:
                result = self._bundle_installer.install_bundle(
                    bundle,
                    serial,
                    token=token,
                    progress=progress,
                    log=log,
                    allow_existing=allow_existing,
                )
            outcome = InstallOutcome(bundle, result=result)
        except OperationCancelled:
            outcome = InstallOutcome(bundle, cancelled=True)
        except InstalledPackageConflict as exc:
            outcome = InstallOutcome(bundle, conflict_package=exc.package_name)
        except BundleInstallError as exc:
            outcome = InstallOutcome(
                bundle,
                error=str(exc),
                failed_obbs=exc.failed_obbs,
            )
        except Exception as exc:
            outcome = InstallOutcome(bundle, error=str(exc))
        self.installOutcomeReady.emit(generation, outcome)

    @Slot()
    def retryFailedObbs(self) -> None:
        bundle = self._retry_bundle
        if bundle is None:
            return
        self._start_bundle_install(bundle, retry_only=True)

    @Slot()
    def continuePackageInstall(self) -> None:
        bundle = self._pending_conflict_bundle
        self._pending_conflict_bundle = None
        if bundle is not None:
            self._start_bundle_install(bundle, allow_existing=True)

    @Slot()
    def cancelPackageInstall(self) -> None:
        if self._pending_conflict_bundle is None:
            return
        self._pending_conflict_bundle = None
        self._set_notice("Install cancelled. The existing Quest app was not changed.")
        self._record_activity("Existing-package install cancelled by the user.")
        self.readinessChanged.emit()

    @Slot()
    def cancelInstall(self) -> None:
        if self._install_token is None:
            return
        self._install_token.cancel()
        self._install_message = "Stopping safely"
        self._set_notice("Stopping the install after the current file…", "warning")
        self.readinessChanged.emit()

    @Slot(int, float, str)
    def _apply_install_progress(self, generation: int, value: float, message: str) -> None:
        if generation != self._install_generation:
            return
        self._install_progress = min(1.0, max(0.0, value))
        self._install_message = message
        if message != self._install_log_step:
            self._install_log_step = message
            self._record_event(
                "INSTALL",
                message,
                (("Progress", f"{round(self._install_progress * 100)}%"),),
            )
        self.readinessChanged.emit()

    @Slot(int, object)
    def _apply_install_outcome(self, generation: int, raw_outcome: object) -> None:
        if generation != self._install_generation or not isinstance(
            raw_outcome, InstallOutcome
        ):
            return
        self._install_token = None
        if raw_outcome.conflict_package:
            self._install_state = "idle"
            self._install_progress = 0.0
            self._pending_conflict_bundle = raw_outcome.bundle
            self._set_notice(
                f"{raw_outcome.conflict_package} is already installed on the Quest.",
                "warning",
            )
            self._record_activity(f"Existing package detected: {raw_outcome.conflict_package}.")
            self.packageConflictRequested.emit(raw_outcome.conflict_package)
        elif raw_outcome.cancelled:
            self._retry_bundle = None
            self._install_state = "idle"
            self._install_progress = 0.0
            self._set_notice(
                "Install cancelled safely. Existing source files were kept.", "warning"
            )
            self._record_event(
                "INSTALL",
                "Install cancelled safely",
                (("After", self._elapsed(self._install_started_at)),),
            )
        elif raw_outcome.error:
            self._retry_bundle = (
                replace(raw_outcome.bundle, obbs=raw_outcome.failed_obbs)
                if raw_outcome.failed_obbs
                else None
            )
            self._install_state = "failed"
            self._install_progress = 0.0
            self._last_failure_report = self._report_in(raw_outcome.bundle.root)
            self._set_notice(f"Install failed: {raw_outcome.error}", "error")
            self._record_event(
                "INSTALL",
                "Install failed",
                (
                    ("After", self._elapsed(self._install_started_at)),
                    ("Reason", raw_outcome.error),
                    ("Failed OBB files", str(len(raw_outcome.failed_obbs))),
                ),
            )
        else:
            self._retry_bundle = None
            assert raw_outcome.result is not None
            self._install_state = "complete"
            self._install_progress = 1.0
            self._last_failure_report = None
            obb_count = len(raw_outcome.result.obbs)
            self._set_notice(
                f"Install verified: APK and {obb_count} OBB file"
                f"{'s' if obb_count != 1 else ''} are on the Quest.",
                "success",
            )
            self._record_event(
                "INSTALL",
                "Install completed and verified on Quest",
                (
                    ("Duration", self._elapsed(self._install_started_at)),
                    ("Package", raw_outcome.result.package_name),
                    ("APK verification", "Installed package confirmed"),
                    ("OBB verification", f"{obb_count} remote file sizes confirmed"),
                    ("Local source", str(raw_outcome.bundle.root)),
                ),
            )
            self._delete_source_after_verified_install(raw_outcome.bundle)
        self.readinessChanged.emit()

    @Slot(QUrl)
    def backupSigningKey(self, url: QUrl) -> None:
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if local:
            self._start_signing_operation("backup", Path(local), replace_existing=False)

    @Slot(QUrl)
    def restoreSigningKey(self, url: QUrl) -> None:
        if self._signing_manager is None or self._signing_busy:
            return
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if not local:
            return
        source = Path(local).expanduser().resolve()
        self._start_signing_operation("restore", source, replace_existing=False)

    @Slot()
    def confirmSigningKeyRestore(self) -> None:
        source = self._pending_restore
        self._pending_restore = None
        if source is not None:
            self._start_signing_operation("restore", source, replace_existing=True)

    @Slot()
    def cancelSigningKeyRestore(self) -> None:
        self._pending_restore = None

    def _start_signing_operation(
        self,
        action: str,
        folder: Path,
        *,
        replace_existing: bool,
    ) -> None:
        if self._signing_manager is None or self.isBusy:
            return
        self._signing_busy = True
        self.signingChanged.emit()
        self.readinessChanged.emit()
        self._set_notice(
            "Creating a private signing-key backup…"
            if action == "backup"
            else "Validating and restoring the signing identity…"
        )
        threading.Thread(
            target=self._signing_operation_worker,
            args=(action, folder, replace_existing),
            daemon=True,
        ).start()

    def _signing_operation_worker(
        self,
        action: str,
        folder: Path,
        replace_existing: bool,
    ) -> None:
        assert self._signing_manager is not None
        try:
            if action == "backup":
                backup = self._signing_manager.backup_to(
                    folder,
                    log=lambda message: self.workerLogReady.emit(f"Signing: {message}"),
                )
                outcome = SigningOperationOutcome(action, backup=backup)
            else:
                restore = self._signing_manager.restore_from(
                    folder,
                    replace_existing=replace_existing,
                    log=lambda message: self.workerLogReady.emit(f"Signing: {message}"),
                )
                outcome = SigningOperationOutcome(action, restore=restore)
        except SigningIdentityAlreadyExists:
            outcome = SigningOperationOutcome(
                action,
                source=folder,
                confirmation_required=True,
            )
        except Exception as exc:
            outcome = SigningOperationOutcome(action, error=str(exc))
        self.signingOutcomeReady.emit(outcome)

    @Slot(object)
    def _apply_signing_outcome(self, raw_outcome: object) -> None:
        if not isinstance(raw_outcome, SigningOperationOutcome):
            return
        self._signing_busy = False
        self.signingChanged.emit()
        self.readinessChanged.emit()
        if raw_outcome.confirmation_required:
            assert raw_outcome.source is not None
            self._pending_restore = raw_outcome.source
            self._set_notice(
                "The backup is valid. Confirm whether it should replace the current identity.",
                "warning",
            )
            self.signingRestoreConfirmationRequested.emit(str(raw_outcome.source))
            return
        if raw_outcome.error:
            self._set_notice(raw_outcome.error, "error")
            self._record_activity(f"Signing {raw_outcome.action} failed: {raw_outcome.error}")
            return
        if raw_outcome.backup is not None:
            destination = raw_outcome.backup.destination
            self._set_notice(f"Signing key backed up to {destination.name}.", "success")
            self._record_activity(f"Signing-key backup created: {destination}")
            return
        assert raw_outcome.restore is not None
        recovery = raw_outcome.restore.recovery
        message = "Signing identity restored and ready for future builds."
        if recovery is not None:
            message += f" The previous identity was kept in {recovery.name}."
        self._set_notice(message, "success")
        self._record_activity(f"Signing identity restored from {raw_outcome.restore.source}")

    def _delete_source_after_verified_install(self, installed: BundleDraft) -> None:
        if not self._settings.delete_source_after_install:
            return
        source = installed.root.resolve()
        report = source / "quest-renamer-report.json"
        if (
            source == Path.home().resolve()
            or source.parent == source
            or installed.apk.parent.resolve() != source
            or not installed.apk.is_file()
            or not report.is_file()
        ):
            self._set_notice(
                "Install succeeded, but the local folder was kept because it is not a "
                "verified Quest APK Renamer output.",
                "warning",
            )
            self._record_activity(f"Installed-folder cleanup safety check rejected: {source}")
            return
        self._set_notice("Install verified. Moving the installed folder to Trash…")
        threading.Thread(
            target=self._source_cleanup_worker,
            args=(source,),
            daemon=True,
        ).start()

    def _source_cleanup_worker(self, source: Path) -> None:
        try:
            if self._move_to_trash is not None:
                self._move_to_trash(source)
                outcome = CleanupOutcome(source, moved_to_trash=True)
            else:
                shutil.rmtree(source)
                outcome = CleanupOutcome(source)
        except OSError as exc:
            outcome = CleanupOutcome(source, str(exc))
        self.sourceCleanupReady.emit(outcome)

    @Slot(object)
    def _apply_source_cleanup(self, raw_outcome: object) -> None:
        if not isinstance(raw_outcome, CleanupOutcome):
            return
        if raw_outcome.error:
            self._set_notice(
                "Install succeeded, but the source folder could not be deleted: "
                f"{raw_outcome.error}",
                "warning",
            )
            self._record_activity(f"Source cleanup failed: {raw_outcome.error}")
            return
        if self._build_result is not None and (
            self._build_result.output_root.resolve() == raw_outcome.source.resolve()
        ):
            self._build_result = None
            self._build_state = "idle"
            self._build_progress = 0.0
        if self._bundle is not None and (
            self._bundle.root.resolve() == raw_outcome.source.resolve()
        ):
            self._bundle = None
            self._package_id = ""
            self._analysis_state = "idle"
            self._preflight = None
            self.bundleChanged.emit()
            self.packageIdChanged.emit()
            self.outputChanged.emit()
        self._set_notice(
            f"Install verified. {raw_outcome.source.name} was "
            + ("moved to Trash." if raw_outcome.moved_to_trash else "deleted."),
            "success",
        )
        self._record_activity(
            f"Cleaned up installed folder after verified install: {raw_outcome.source}"
        )
        self.readinessChanged.emit()

    def _refresh_preflight(self) -> None:
        request = self._build_request()
        if self._preflight_service is None or request is None:
            self.readinessChanged.emit()
            return
        try:
            self._preflight = self._preflight_service.check(request, device=self._device)
        except OSError as exc:
            self._preflight = None
            self._set_notice(f"The build checks could not finish: {exc}", "error")
            self._record_activity(f"Preflight failed: {exc}")
            self.readinessChanged.emit()
            return
        tone = (
            "success" if self._preflight.ready and not self._preflight.warnings else "warning"
        )
        self._set_notice(self._preflight.summary, tone)
        self.readinessChanged.emit()

    @Slot(str)
    def applyTag(self, tag: str) -> None:
        if not self._bundle or not self._bundle.package_name:
            self._set_notice(
                "APK analysis must identify the original package first.",
                "warning",
            )
            return
        try:
            self.setPackageId(with_tag(self._bundle.package_name, tag))
        except ValueError as exc:
            self._set_notice(str(exc), "error")

    @Slot()
    def requestBuild(self) -> None:
        if self._build_state == "running":
            assert self._build_token is not None
            self._build_token.cancel()
            self._build_message = "Stopping after the current safe point"
            self._set_notice("Cancelling safely…", "warning")
            self.readinessChanged.emit()
            return
        if self._build_result is not None:
            self._open_local_path(self._build_result.output_root, "finished folder")
            return
        if not self._can_build():
            self._set_notice(
                self._package_error() or "Choose a game folder first.",
                "warning",
            )
            return
        assert self._build_engine is not None
        request = self._build_request()
        assert request is not None
        self._build_generation += 1
        generation = self._build_generation
        token = CancellationToken()
        self._build_token = token
        self._build_started_at = time.monotonic()
        self._build_log_step = "Preparing isolated workspace"
        self._build_state = "running"
        self._build_progress = 0.0
        self._build_message = "Preparing isolated workspace"
        self._last_failure_report = None
        patch_only = self._patch_only_build()
        if patch_only and request.replace_source:
            self._set_notice(
                "Applying the patch and verifying it before replacing the source."
            )
        elif patch_only:
            self._set_notice(
                "Applying the patch in a separate copy. The source stays untouched."
            )
        elif request.replace_source:
            self._set_notice(
                "Building and verifying the replacement before changing the source."
            )
        else:
            self._set_notice("Building a separate copy. The source stays untouched.")
        self._record_event(
            "BUILD",
            "Renamed bundle build started",
            (
                ("Source", str(request.source.root)),
                ("Output", str(request.output_root)),
                (
                    "Package ID",
                    f"{request.source.package_name} → {request.package_name}",
                ),
                (
                    "Output mode",
                    "Replace source" if request.replace_source else "Separate copy",
                ),
                ("Signing", "Enabled" if request.sign_apk else "Disabled"),
                ("OBB files", str(len(request.source.obbs) if request.copy_obbs else 0)),
                ("Patches", ", ".join(request.patches) or "None"),
            ),
        )
        self.readinessChanged.emit()
        threading.Thread(
            target=self._build_worker,
            args=(generation, request, token),
            daemon=True,
        ).start()

    def _build_worker(
        self,
        generation: int,
        request: BuildRequest,
        token: CancellationToken,
    ) -> None:
        assert self._build_engine is not None
        try:
            result = self._build_engine.build(
                request,
                token=token,
                progress=lambda value, message: self.buildProgressReady.emit(
                    generation, value, message
                ),
                log=lambda message: self.workerLogReady.emit(f"Build: {message}"),
            )
            outcome = BuildOutcome(result=result)
        except BuildError as exc:
            outcome = BuildOutcome(error=str(exc), partial_output=exc.partial_output)
        except OperationCancelled:
            outcome = BuildOutcome(error="Build cancelled safely.")
        except Exception as exc:  # adapter failures become a controlled UI result
            outcome = BuildOutcome(error=str(exc))
        self.buildOutcomeReady.emit(generation, outcome)

    @Slot(int, float, str)
    def _apply_build_progress(self, generation: int, value: float, message: str) -> None:
        if generation != self._build_generation:
            return
        self._build_progress = min(1.0, max(0.0, value))
        self._build_message = message
        if message != self._build_log_step:
            self._build_log_step = message
            self._record_event(
                "BUILD",
                message,
                (("Progress", f"{round(self._build_progress * 100)}%"),),
            )
        self.readinessChanged.emit()

    @Slot(int, object)
    def _apply_build_outcome(self, generation: int, raw_outcome: object) -> None:
        if generation != self._build_generation or not isinstance(raw_outcome, BuildOutcome):
            return
        self._build_token = None
        if raw_outcome.result is None:
            self._build_state = "failed"
            self._build_progress = 0.0
            message = raw_outcome.error or "The build did not finish."
            tone = "warning" if "cancelled" in message.lower() else "error"
            if raw_outcome.partial_output is not None:
                self._last_failure_report = self._report_in(raw_outcome.partial_output)
            self._set_notice(message, tone)
            self._record_event(
                "BUILD",
                "Build stopped",
                (
                    ("After", self._elapsed(self._build_started_at)),
                    ("Reason", message),
                    (
                        "Partial output",
                        str(raw_outcome.partial_output)
                        if raw_outcome.partial_output
                        else "None",
                    ),
                ),
            )
            self._partial_output = raw_outcome.partial_output
            if self._partial_output is not None:
                self.partialOutputChanged.emit()
            self.readinessChanged.emit()
            return
        self._build_result = raw_outcome.result
        self._last_failure_report = None
        self._build_state = "complete"
        self._build_progress = 1.0
        self._build_message = "Build complete"
        source_was_replaced = self._bundle is not None and (
            raw_outcome.result.output_root.resolve() == self._bundle.root.resolve()
        )
        if source_was_replaced:
            if self._bundle is not None:
                self._bundle = replace(
                    self._bundle,
                    root=raw_outcome.result.output_root,
                    apk=raw_outcome.result.apk,
                    obbs=raw_outcome.result.obbs,
                    manifest=raw_outcome.result.manifest,
                    package_name=self._package_id,
                )
                self.bundleChanged.emit()
                self.outputChanged.emit()
            if raw_outcome.result.recovery_root is None:
                self._set_notice("Source replaced with the signed, verified bundle.", "success")
            else:
                self._set_notice(
                    "Source replaced. Trash was unavailable, so the original was kept "
                    f"as {raw_outcome.result.recovery_root.name}.",
                    "warning",
                )
                self._record_activity(
                    f"Original source recovery folder: {raw_outcome.result.recovery_root}"
                )
        else:
            message = (
                "Patched copy built, signed, and verified."
                if self._patch_only_build()
                else "Renamed copy built, signed, and verified."
            )
            self._set_notice(message, "success")
        text_report = raw_outcome.result.text_report or (
            raw_outcome.result.output_root / "RENAME-REPORT.txt"
        )
        self._record_event(
            "BUILD",
            "Build completed and verified",
            (
                ("Duration", self._elapsed(self._build_started_at)),
                ("Output", str(raw_outcome.result.output_root)),
                ("APK", raw_outcome.result.apk.name),
                ("OBB files", str(len(raw_outcome.result.obbs))),
                ("References changed", str(raw_outcome.result.rewrite.changed_occurrences)),
                ("Decoded files changed", str(raw_outcome.result.rewrite.changed_files)),
                ("Readable report", str(text_report)),
                ("JSON report", str(raw_outcome.result.report)),
            ),
        )
        self.signingChanged.emit()
        self.readinessChanged.emit()
        if (
            self._settings.sign_apks
            and self._settings.key_backup_reminder
            and self._signing_manager is not None
        ):
            state = self._signing_manager.state()
            if state.complete and not state.backed_up:
                self.signingBackupReminderRequested.emit()

    @Slot()
    def discardPartialBuild(self) -> None:
        partial = self._partial_output
        if partial is None:
            return
        # Only engine-created, explicitly returned staging folders are eligible.
        if ".staging-" not in partial.name:
            self._set_notice(
                "The partial folder was not removed because it was not recognized.", "error"
            )
            return
        try:
            shutil.rmtree(partial)
        except OSError as exc:
            self._set_notice(f"The partial folder could not be removed: {exc}", "error")
            return
        clear_build_recovery(self._paths.build_recovery_file, partial)
        self._record_activity(f"Removed partial build: {partial}")
        self._partial_output = None
        self.partialOutputChanged.emit()

    @Slot()
    def keepPartialBuild(self) -> None:
        if self._partial_output is not None:
            self._record_activity(f"Kept partial build: {self._partial_output}")
            clear_build_recovery(
                self._paths.build_recovery_file,
                self._partial_output,
            )
        self._partial_output = None
        self.partialOutputChanged.emit()

    @Slot()
    def openPartialBuild(self) -> None:
        partial = self._partial_output
        if partial is None or not partial.is_dir():
            self._set_notice("The partial build folder is no longer available.", "warning")
            self.keepPartialBuild()
            return
        if not self._open_local_path(partial, "partial build folder"):
            return
        self._record_activity(f"Opened and kept partial build: {partial}")
        clear_build_recovery(self._paths.build_recovery_file, partial)
        self._partial_output = None
        self.partialOutputChanged.emit()

    @Slot()
    def startOver(self) -> None:
        if self._analysis_token is not None:
            self._analysis_token.cancel()
            self._analysis_token = None
        self._analysis_generation += 1
        if self._build_token is not None:
            self._build_token.cancel()
            self._build_token = None
        self._build_generation += 1
        self._bundle = None
        self._package_id = ""
        self._analysis_state = "idle"
        self._analysis_progress = 0.0
        self._preflight = None
        self._build_state = "idle"
        self._build_progress = 0.0
        self._build_result = None
        self._output_parent = None
        self._older_firmware_supported = False
        if self._install_token is not None:
            self._install_token.cancel()
            self._install_token = None
        self._install_generation += 1
        self._install_state = "idle"
        self._retry_bundle = None
        self._pending_conflict_bundle = None
        self._pending_restore = None
        self.bundleChanged.emit()
        self.packageIdChanged.emit()
        self.readinessChanged.emit()
        self._set_notice("Choose a game folder to begin.")
        self._record_activity("Workspace cleared.")
