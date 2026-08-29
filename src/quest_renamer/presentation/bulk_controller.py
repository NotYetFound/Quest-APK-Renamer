"""Independent QML-facing controller for sequential bulk build and install jobs."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from quest_renamer.domain.analysis import ApkAnalysis
from quest_renamer.domain.build import BuildError, BuildResult
from quest_renamer.domain.bulk import package_with_suffix
from quest_renamer.domain.models import BuildRequest, BundleDraft, DeviceSnapshot
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure.desktop_open import open_local_path
from quest_renamer.infrastructure.local_bundles import BundleSelectionError
from quest_renamer.infrastructure.older_firmware_patch import PATCH_ID
from quest_renamer.infrastructure.settings_store import JsonSettingsStore
from quest_renamer.presentation.shared import write_system_clipboard
from quest_renamer.services.contracts import (
    ApkAnalyzer,
    BuildEngine,
    BulkBundleInspector,
    BundleInstaller,
    PreflightService,
)
from quest_renamer.services.preflight import default_output_folder


@dataclass(frozen=True, slots=True)
class BulkEntry:
    source: BundleDraft
    bundle: BundleDraft
    current_package: str
    target_package: str
    has_legacy_loader: bool = False
    status: str = "Ready"
    detail: str = "Ready for the queue"
    tone: str = "neutral"
    progress: float = 0.0
    built: bool = False
    installed: bool = False


@dataclass(frozen=True, slots=True)
class BulkOperationOutcome:
    mode: str
    successes: int
    failures: int
    cancelled: bool
    details: tuple[str, ...] = ()


class BulkQueueModel(QAbstractListModel):
    FolderNameRole = int(Qt.ItemDataRole.UserRole) + 1
    FolderPathRole = FolderNameRole + 1
    ApkNameRole = FolderNameRole + 2
    ObbSummaryRole = FolderNameRole + 3
    CurrentPackageRole = FolderNameRole + 4
    TargetPackageRole = FolderNameRole + 5
    StatusRole = FolderNameRole + 6
    DetailRole = FolderNameRole + 7
    ToneRole = FolderNameRole + 8
    ProgressRole = FolderNameRole + 9
    BuiltRole = FolderNameRole + 10
    InstalledRole = FolderNameRole + 11

    _role_names: ClassVar[dict[int, QByteArray]] = {
        FolderNameRole: QByteArray(b"folderName"),
        FolderPathRole: QByteArray(b"folderPath"),
        ApkNameRole: QByteArray(b"apkName"),
        ObbSummaryRole: QByteArray(b"obbSummary"),
        CurrentPackageRole: QByteArray(b"currentPackage"),
        TargetPackageRole: QByteArray(b"targetPackage"),
        StatusRole: QByteArray(b"itemStatus"),
        DetailRole: QByteArray(b"itemDetail"),
        ToneRole: QByteArray(b"itemTone"),
        ProgressRole: QByteArray(b"itemProgress"),
        BuiltRole: QByteArray(b"itemBuilt"),
        InstalledRole: QByteArray(b"itemInstalled"),
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[BulkEntry] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return self._role_names

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        values: dict[int, Any] = {
            self.FolderNameRole: entry.source.root.name,
            self.FolderPathRole: str(entry.source.root),
            self.ApkNameRole: entry.source.apk.name,
            self.ObbSummaryRole: (
                f"{len(entry.source.obbs)} OBB file{'s' if len(entry.source.obbs) != 1 else ''}"
                if entry.source.obbs
                else "No OBB files"
            ),
            self.CurrentPackageRole: entry.current_package,
            self.TargetPackageRole: entry.target_package,
            self.StatusRole: entry.status,
            self.DetailRole: entry.detail,
            self.ToneRole: entry.tone,
            self.ProgressRole: entry.progress,
            self.BuiltRole: entry.built,
            self.InstalledRole: entry.installed,
        }
        return values.get(role)

    def entries(self) -> tuple[BulkEntry, ...]:
        return tuple(self._entries)

    def append_many(self, entries: Iterable[BulkEntry]) -> int:
        additions = list(entries)
        if not additions:
            return 0
        first = len(self._entries)
        self.beginInsertRows(QModelIndex(), first, first + len(additions) - 1)
        self._entries.extend(additions)
        self.endInsertRows()
        return len(additions)

    def replace_entry(self, row: int, entry: BulkEntry) -> None:
        if not 0 <= row < len(self._entries):
            return
        self._entries[row] = entry
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, list(self._role_names))

    def remove(self, row: int) -> bool:
        if not 0 <= row < len(self._entries):
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        self._entries.pop(row)
        self.endRemoveRows()
        return True

    def clear(self) -> None:
        if not self._entries:
            return
        self.beginResetModel()
        self._entries.clear()
        self.endResetModel()


class BulkController(QObject):
    queueChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    optionsChanged = Signal()
    overviewChanged = Signal()
    confirmationRequested = Signal(str, str, str)
    entriesReady = Signal(object, object)
    itemReady = Signal(int, object)
    progressReady = Signal(float, str)
    operationReady = Signal(object)
    activityMessage = Signal(str)

    def __init__(
        self,
        *,
        inspector: BulkBundleInspector,
        analyzer: ApkAnalyzer | None,
        preflight_service: PreflightService,
        build_engine: BuildEngine,
        bundle_installer: BundleInstaller,
        settings_store: JsonSettingsStore,
        device_snapshot: Callable[[], DeviceSnapshot],
        external_busy: Callable[[], bool] | None = None,
        move_to_trash: Callable[[Path], None] | None = None,
        path_opener: Callable[[Path], bool] | None = None,
        clipboard_writer: Callable[[str], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = BulkQueueModel(self)
        self._path_opener = path_opener or open_local_path
        self._clipboard_writer = clipboard_writer or write_system_clipboard
        self._inspector = inspector
        self._analyzer = analyzer
        self._preflight_service = preflight_service
        self._build_engine = build_engine
        self._bundle_installer = bundle_installer
        self._settings_store = settings_store
        self._device_snapshot = device_snapshot
        self._external_busy = external_busy or (lambda: False)
        self._move_to_trash = move_to_trash
        self._suffix = "a"
        self._suffix_error = ""
        self._replace_sources = False
        self._cleanup_after_install = False
        self._busy = False
        self._adding = False
        self._status = "Add several APKs or game folders to begin."
        self._progress = 0.0
        self._pending_mode = ""
        self._token: CancellationToken | None = None
        self._overview_title = ""
        self._overview_text = ""
        self.entriesReady.connect(self._apply_entries)
        self.itemReady.connect(self._apply_item)
        self.progressReady.connect(self._apply_progress)
        self.operationReady.connect(self._apply_operation)

    @Property(QObject, constant=True)
    def items(self) -> QObject:
        return self._model

    @Property(int, notify=queueChanged)
    def count(self) -> int:
        return self._model.rowCount()

    @Property(str, notify=queueChanged)
    def countLabel(self) -> str:
        count = self._model.rowCount()
        return f"{count} game" + ("" if count == 1 else "s")

    @Property(bool, notify=busyChanged)
    def isBusy(self) -> bool:
        return self.has_active_work()

    def has_active_work(self) -> bool:
        return self._busy or self._adding

    @Property(bool, notify=queueChanged)
    def canBuild(self) -> bool:
        entries = self._model.entries()
        return (
            bool(entries)
            and not self.has_active_work()
            and any(not item.built for item in entries)
        )

    @Property(bool, notify=queueChanged)
    def canInstall(self) -> bool:
        entries = self._model.entries()
        return (
            bool(entries)
            and not self.has_active_work()
            and any(not item.installed for item in entries)
        )

    @Property(bool, notify=queueChanged)
    def hasInstalled(self) -> bool:
        return any(item.installed for item in self._model.entries())

    @Property(bool, notify=queueChanged)
    def canEditSuffix(self) -> bool:
        return not self.has_active_work() and not any(
            item.built for item in self._model.entries()
        )

    @Property(str, notify=optionsChanged)
    def suffix(self) -> str:
        return self._suffix

    @Property(str, notify=optionsChanged)
    def suffixError(self) -> str:
        return self._suffix_error

    @Property(bool, notify=optionsChanged)
    def replaceSources(self) -> bool:
        return self._replace_sources

    @Property(bool, notify=optionsChanged)
    def cleanupAfterInstall(self) -> bool:
        return self._cleanup_after_install

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(float, notify=statusChanged)
    def progress(self) -> float:
        return self._progress

    @Property(str, notify=overviewChanged)
    def overviewTitle(self) -> str:
        return self._overview_title

    @Property(str, notify=overviewChanged)
    def overviewText(self) -> str:
        return self._overview_text

    @Property(bool, notify=overviewChanged)
    def hasOverview(self) -> bool:
        return bool(self._overview_title)

    @Slot(str)
    def setSuffix(self, value: str) -> None:
        if self.has_active_work() or any(item.built for item in self._model.entries()):
            return
        value = value.strip()
        try:
            package_with_suffix("com.example.game", value)
            for entry in self._model.entries():
                package_with_suffix(entry.current_package, value)
        except ValueError as exc:
            self._suffix = value
            self._suffix_error = str(exc)
            self.optionsChanged.emit()
            self.queueChanged.emit()
            return
        self._suffix = value
        self._suffix_error = ""
        for row, entry in enumerate(self._model.entries()):
            self._model.replace_entry(
                row,
                replace(
                    entry,
                    target_package=package_with_suffix(entry.current_package, value),
                ),
            )
        self.optionsChanged.emit()
        self.queueChanged.emit()

    @Slot(bool)
    def setReplaceSources(self, value: bool) -> None:
        if self.has_active_work():
            return
        self._replace_sources = value
        self.optionsChanged.emit()

    @Slot(bool)
    def setCleanupAfterInstall(self, value: bool) -> None:
        if self.has_active_work():
            return
        self._cleanup_after_install = value
        self.optionsChanged.emit()

    @Slot(QUrl)
    def addFolder(self, url: QUrl) -> None:
        path = self._path_from_url(url)
        if path is not None:
            self._start_add((path,), scan_parent=False)

    @Slot("QVariantList")
    def addApks(self, urls: list[object]) -> None:
        paths = {path for value in urls if (path := self._path_from_url(value)) is not None}
        self._start_add(tuple(sorted(paths)), scan_parent=False)

    @Slot("QVariantList")
    def addDropped(self, urls: list[object]) -> None:
        paths: set[Path] = set()
        for value in urls:
            path = self._path_from_url(value)
            if path is None:
                continue
            paths.add(path if path.is_dir() or path.suffix.lower() == ".apk" else path.parent)
        self._start_add(tuple(sorted(paths)), scan_parent=False)

    @Slot(QUrl)
    def scanParent(self, url: QUrl) -> None:
        path = self._path_from_url(url)
        if path is not None:
            self._start_add((path,), scan_parent=True)

    @Slot(int)
    def removeItem(self, row: int) -> None:
        if not self.has_active_work() and self._model.remove(row):
            self._queue_updated()

    @Slot(int)
    def openOutput(self, row: int) -> None:
        entries = self._model.entries()
        if not 0 <= row < len(entries):
            return
        entry = entries[row]
        folder = entry.bundle.root if entry.built else entry.source.root
        if not folder.is_dir():
            self._set_status(f"{folder.name} is no longer available.")
            return
        if not self._path_opener(folder):
            self._set_status(f"Could not open {folder}.")

    @Slot(int)
    def copyDetail(self, row: int) -> None:
        entries = self._model.entries()
        if not 0 <= row < len(entries):
            return
        entry = entries[row]
        text = f"{entry.source.root.name}: {entry.status} — {entry.detail}"
        if self._clipboard_writer(text):
            self._set_status("Entry details copied to the clipboard.")
        else:
            self._set_status("The clipboard is unavailable in this session.")

    @Slot()
    def removeFinished(self) -> None:
        """Drop installed entries so the queue only shows remaining work."""
        if self.has_active_work():
            return
        removed = False
        for row in range(self._model.rowCount() - 1, -1, -1):
            entry = self._model.entries()[row]
            if entry.installed and self._model.remove(row):
                removed = True
        if removed:
            self._queue_updated()

    @Slot()
    def clear(self) -> None:
        if self.has_active_work():
            return
        self._model.clear()
        self._overview_title = ""
        self._overview_text = ""
        self.overviewChanged.emit()
        self._queue_updated()

    @Slot()
    def dismissOverview(self) -> None:
        self._overview_title = ""
        self._overview_text = ""
        self.overviewChanged.emit()

    @Slot()
    def requestBuild(self) -> None:
        if not self._operation_available() or not self.canBuild:
            return
        if self._suffix_error:
            self._set_status(self._suffix_error)
            return
        targets = [item.target_package for item in self._model.entries() if not item.built]
        if len(targets) != len(set(targets)):
            self._set_status("Two queued games would receive the same package ID.")
            return
        self._pending_mode = "build"
        replacement = (
            " Each verified result will replace its source folder."
            if self._replace_sources
            else " Original folders will stay unchanged."
        )
        self.confirmationRequested.emit(
            "build",
            "Build the queued games?",
            f"{len(targets)} game{'s' if len(targets) != 1 else ''} will run one at a time."
            + replacement,
        )

    @Slot()
    def requestInstall(self) -> None:
        if not self._operation_available() or not self.canInstall:
            return
        device = self._device_snapshot()
        if not device.connected or not device.serial:
            self._set_status("Connect and authorize one Quest before starting the queue.")
            return
        entries = [item for item in self._model.entries() if not item.installed]
        required = sum(item.bundle.total_size + 128 * 1024 * 1024 for item in entries)
        space_note = ""
        if device.free_bytes is not None and required > device.free_bytes:
            space_note = " The full queue may not fit in the available Quest storage."
        unbuilt = [item for item in entries if not item.built]
        if unbuilt:
            space_note += (
                f" {len(unbuilt)} game{'s' if len(unbuilt) != 1 else ''} "
                f"{'have' if len(unbuilt) != 1 else 'has'} not been built yet and will be "
                "installed unchanged under the original package ID."
            )
        cleanup_note = (
            " Verified local output folders will then move to Trash."
            if self._cleanup_after_install
            else " Local folders will be kept."
        )
        self._pending_mode = "install"
        self.confirmationRequested.emit(
            "install",
            "Install the queued games?",
            f"{len(entries)} game{'s' if len(entries) != 1 else ''} will install one at a "
            "time. Existing package IDs will be treated as updates."
            + space_note
            + cleanup_note,
        )

    @Slot()
    def confirmOperation(self) -> None:
        mode = self._pending_mode
        self._pending_mode = ""
        if mode == "build":
            self._start_operation("build")
        elif mode == "install":
            self._start_operation("install")

    @Slot()
    def cancelConfirmation(self) -> None:
        self._pending_mode = ""

    @Slot()
    def cancel(self) -> None:
        if self._token is not None:
            self._token.cancel()
            self._set_status("Stopping after the current safe point…", self._progress)

    def _start_add(self, paths: tuple[Path, ...], *, scan_parent: bool) -> None:
        if not paths or self.has_active_work() or self._external_busy():
            return
        self._adding = True
        self.busyChanged.emit()
        self.queueChanged.emit()
        self._set_status("Checking selected game folders…", 0.0)
        threading.Thread(
            target=self._add_worker,
            args=(paths, scan_parent),
            daemon=True,
        ).start()

    def _add_worker(self, roots: tuple[Path, ...], scan_parent: bool) -> None:
        candidates: list[Path] = []
        errors: list[str] = []
        if scan_parent:
            parent = roots[0]
            try:
                direct_apks = tuple(parent.glob("*.apk"))
                candidates = (
                    [parent]
                    if direct_apks
                    else [path for path in sorted(parent.iterdir()) if path.is_dir()]
                )
            except OSError as exc:
                errors.append(str(exc))
        else:
            candidates = list(roots)

        additions: list[BulkEntry] = []
        for root in candidates:
            try:
                bundle = (
                    self._inspector.inspect_apk(root)
                    if root.is_file()
                    else self._inspector.inspect_folder(root)
                )
                analysis: ApkAnalysis | None = None
                analysis_warning = ""
                if self._analyzer is not None:
                    try:
                        analysis = self._analyzer.analyze(bundle.apk)
                    except Exception as exc:
                        analysis_warning = f"APK analysis warning: {exc}"
                if analysis is not None:
                    bundle = replace(
                        bundle,
                        package_name=analysis.package_name,
                        version_code=analysis.version_code or bundle.version_code,
                        game_name=bundle.game_name or analysis.app_label,
                        signer_identity=analysis.signer_identity,
                    )
                if not bundle.package_name:
                    raise BundleSelectionError("The package ID could not be detected.")
                target = package_with_suffix(bundle.package_name, self._suffix)
                additions.append(
                    BulkEntry(
                        source=bundle,
                        bundle=bundle,
                        current_package=bundle.package_name,
                        target_package=target,
                        has_legacy_loader=(
                            analysis.has_legacy_loader if analysis is not None else False
                        ),
                        detail=analysis_warning or "Ready for the queue",
                        tone="warning" if analysis_warning else "neutral",
                    )
                )
            except (BundleSelectionError, OSError, ValueError) as exc:
                errors.append(f"{root.name}: {exc}")
            except Exception as exc:  # a broken adapter must not wedge the queue
                errors.append(f"{root.name}: unexpected error: {exc}")
        self.entriesReady.emit(tuple(additions), tuple(errors))

    @Slot(object, object)
    def _apply_entries(self, raw_entries: object, raw_errors: object) -> None:
        entry_values = raw_entries if isinstance(raw_entries, (tuple, list)) else ()
        error_values = raw_errors if isinstance(raw_errors, (tuple, list)) else ()
        entries = tuple(item for item in entry_values if isinstance(item, BulkEntry))
        errors = tuple(str(item) for item in error_values)
        existing = {item.source.root.resolve() for item in self._model.entries()}
        additions: list[BulkEntry] = []
        for entry in entries:
            root = entry.source.root.resolve()
            if root in existing:
                continue
            if any(root in other.parents or other in root.parents for other in existing):
                errors += (f"{root.name}: nested queue folders are not allowed.",)
                continue
            existing.add(root)
            additions.append(entry)
        count = self._model.append_many(additions)
        self._adding = False
        self.busyChanged.emit()
        self._queue_updated()
        if errors:
            self._set_status(
                f"Added {count}. {len(errors)} item{'s' if len(errors) != 1 else ''} "
                f"need attention: {errors[0]}"
            )
        elif count:
            self._set_status(f"Added {count} game{'s' if count != 1 else ''} to the queue.")
        else:
            self._set_status("Those games are already in the queue.")

    def _start_operation(self, mode: str) -> None:
        if not self._operation_available():
            return
        self._busy = True
        self._token = CancellationToken()
        self._overview_title = ""
        self._overview_text = ""
        self.busyChanged.emit()
        self.queueChanged.emit()
        self.overviewChanged.emit()
        self._set_status(
            "Preparing bulk build…" if mode == "build" else "Preparing bulk install…",
            0.0,
        )
        entries = self._model.entries()
        target = self._build_worker if mode == "build" else self._install_worker
        threading.Thread(target=target, args=(entries, self._token), daemon=True).start()

    def _build_worker(
        self,
        entries: tuple[BulkEntry, ...],
        token: CancellationToken,
    ) -> None:
        settings = self._settings_store.load()
        rows = [(row, item) for row, item in enumerate(entries) if not item.built]
        successes = 0
        failures = 0
        details: list[str] = []
        cancelled = False
        for position, (row, entry) in enumerate(rows):
            if token.is_cancelled():
                cancelled = True
                break
            self.itemReady.emit(
                row,
                replace(entry, status="Building", detail="Preparing…", tone="active"),
            )
            try:
                output = (
                    entry.source.root
                    if self._replace_sources
                    else self._unique_output(default_output_folder(entry.source.root))
                )
            except OSError as exc:
                # A bad output location must fail this item, not abandon the queue.
                self.itemReady.emit(
                    row,
                    replace(
                        entry,
                        status="Failed",
                        detail=f"Output folder unavailable: {exc}",
                        tone="error",
                    ),
                )
                continue
            request = BuildRequest(
                source=entry.source,
                package_name=entry.target_package,
                output_root=output,
                copy_obbs=settings.copy_obbs or self._replace_sources,
                sign_apk=settings.sign_apks,
                patches=(PATCH_ID,)
                if settings.older_firmware_patch and entry.has_legacy_loader
                else (),
                replace_source=self._replace_sources,
                app_label_suffix=(
                    settings.label_suffix if settings.change_display_name else ""
                ),
                rename_java_packages=settings.rename_java_packages,
            )
            try:
                preflight = self._preflight_service.check(
                    request,
                    device=self._device_snapshot(),
                )
                if not preflight.ready:
                    raise BuildError(preflight.summary)

                def progress(
                    value: float,
                    message: str,
                    *,
                    item_row: int = row,
                    item_position: int = position,
                    item_entry: BulkEntry = entry,
                ) -> None:
                    overall = (item_position + value) / max(1, len(rows))
                    self.progressReady.emit(overall, message)
                    self.itemReady.emit(
                        item_row,
                        replace(
                            item_entry,
                            status="Building",
                            detail=message,
                            tone="active",
                            progress=value,
                        ),
                    )

                def log_build(message: str, name: str = entry.source.root.name) -> None:
                    self.activityMessage.emit(f"Bulk build {name}: {message}")

                result = self._build_engine.build(
                    request,
                    token=token,
                    progress=progress,
                    log=log_build,
                )
                finished = self._bundle_from_result(entry, result)
                completed = replace(
                    entry,
                    bundle=finished,
                    status="Built",
                    detail="Signed and verified",
                    tone="success",
                    progress=1.0,
                    built=True,
                    installed=False,
                )
                self.itemReady.emit(row, completed)
                successes += 1
                self.activityMessage.emit(f"Bulk build complete: {result.output_root}")
            except Exception as exc:  # one failed game must never stop the queue
                if token.is_cancelled() or isinstance(exc, OperationCancelled):
                    cancelled = True
                    self.itemReady.emit(
                        row,
                        replace(
                            entry,
                            status="Cancelled",
                            detail="Stopped safely",
                            tone="warning",
                        ),
                    )
                    break
                failures += 1
                detail = str(exc) or exc.__class__.__name__
                details.append(f"{entry.source.root.name}: {detail}")
                self.itemReady.emit(
                    row,
                    replace(entry, status="Failed", detail=detail, tone="error"),
                )
        self.operationReady.emit(
            BulkOperationOutcome("build", successes, failures, cancelled, tuple(details))
        )

    def _install_worker(
        self,
        entries: tuple[BulkEntry, ...],
        token: CancellationToken,
    ) -> None:
        rows = [(row, item) for row, item in enumerate(entries) if not item.installed]
        successes = 0
        failures = 0
        details: list[str] = []
        cancelled = False
        for position, (row, entry) in enumerate(rows):
            if token.is_cancelled():
                cancelled = True
                break
            # Re-read the headset state for every game; a disconnect mid-queue must
            # stop cleanly instead of failing each remaining entry in turn.
            device = self._device_snapshot()
            if not device.connected or not device.serial:
                failures += len(rows) - position
                details.append("Quest disconnected; remaining games were skipped.")
                for skipped_row, skipped in rows[position:]:
                    self.itemReady.emit(
                        skipped_row,
                        replace(
                            skipped,
                            status="Skipped",
                            detail="Quest disconnected before this game was installed",
                            tone="warning",
                        ),
                    )
                break
            self.itemReady.emit(
                row,
                replace(entry, status="Installing", detail="Preparing…", tone="active"),
            )
            try:

                def progress(
                    value: float,
                    message: str,
                    *,
                    item_row: int = row,
                    item_position: int = position,
                    item_entry: BulkEntry = entry,
                ) -> None:
                    overall = (item_position + value) / max(1, len(rows))
                    self.progressReady.emit(overall, message)
                    self.itemReady.emit(
                        item_row,
                        replace(
                            item_entry,
                            status="Installing",
                            detail=message,
                            tone="active",
                            progress=value,
                        ),
                    )

                def log_install(message: str, name: str = entry.bundle.root.name) -> None:
                    self.activityMessage.emit(f"Bulk install {name}: {message}")

                self._bundle_installer.install_bundle(
                    entry.bundle,
                    device.serial,
                    token=token,
                    progress=progress,
                    log=log_install,
                    allow_existing=True,
                )
                cleanup_detail = ""
                tone = "success"
                if self._cleanup_after_install:
                    try:
                        self._cleanup_installed_bundle(entry.bundle)
                        cleanup_detail = " • local folder moved to Trash"
                    except OSError as exc:
                        cleanup_detail = f" • local folder kept: {exc}"
                        tone = "warning"
                self.itemReady.emit(
                    row,
                    replace(
                        entry,
                        status="Installed",
                        detail="APK and OBB files verified" + cleanup_detail,
                        tone=tone,
                        progress=1.0,
                        installed=True,
                    ),
                )
                successes += 1
                self.activityMessage.emit(f"Bulk install verified: {entry.bundle.root}")
            except Exception as exc:  # one failed game must never stop the queue
                if token.is_cancelled() or isinstance(exc, OperationCancelled):
                    cancelled = True
                    self.itemReady.emit(
                        row,
                        replace(
                            entry,
                            status="Cancelled",
                            detail="Stopped safely",
                            tone="warning",
                        ),
                    )
                    break
                failures += 1
                detail = str(exc) or exc.__class__.__name__
                details.append(f"{entry.bundle.root.name}: {detail}")
                self.itemReady.emit(
                    row,
                    replace(entry, status="Failed", detail=detail, tone="error"),
                )
        self.operationReady.emit(
            BulkOperationOutcome("install", successes, failures, cancelled, tuple(details))
        )

    @Slot(int, object)
    def _apply_item(self, row: int, raw_entry: object) -> None:
        if not isinstance(raw_entry, BulkEntry):
            return
        entries = self._model.entries()
        previous = entries[row] if 0 <= row < len(entries) else None
        self._model.replace_entry(row, raw_entry)
        # Progress ticks only touch the row; queue-wide flags change on status edges.
        if previous is None or (
            previous.status,
            previous.built,
            previous.installed,
        ) != (raw_entry.status, raw_entry.built, raw_entry.installed):
            self.queueChanged.emit()

    @Slot(float, str)
    def _apply_progress(self, value: float, message: str) -> None:
        self._set_status(message, value)

    @Slot(object)
    def _apply_operation(self, raw_outcome: object) -> None:
        if not isinstance(raw_outcome, BulkOperationOutcome):
            return
        self._busy = False
        self._token = None
        self._progress = 1.0 if not raw_outcome.cancelled else self._progress
        action = "build" if raw_outcome.mode == "build" else "install"
        self._overview_title = (
            f"Bulk {action} cancelled" if raw_outcome.cancelled else f"Bulk {action} complete"
        )
        summary = f"{raw_outcome.successes} succeeded • {raw_outcome.failures} failed"
        if raw_outcome.cancelled:
            summary += " • remaining games were not started"
        if raw_outcome.details:
            summary += "\n" + "\n".join(raw_outcome.details[:5])
        self._overview_text = summary
        self._status = summary.splitlines()[0]
        self.busyChanged.emit()
        self.queueChanged.emit()
        self.statusChanged.emit()
        self.overviewChanged.emit()
        self.activityMessage.emit(f"{self._overview_title}: {summary}")

    def _cleanup_installed_bundle(self, bundle: BundleDraft) -> None:
        root = bundle.root.resolve()
        if (
            self._move_to_trash is None
            or root == Path.home().resolve()
            or root.parent == root
            or bundle.apk.parent.resolve() != root
            or not bundle.apk.is_file()
            or not (root / "quest-renamer-report.json").is_file()
        ):
            raise OSError("not a safe app-created output")
        self._move_to_trash(root)

    def _bundle_from_result(self, entry: BulkEntry, result: BuildResult) -> BundleDraft:
        return BundleDraft(
            root=result.output_root,
            apk=result.apk,
            obbs=result.obbs,
            manifest=result.manifest,
            game_name=entry.source.game_name,
            package_name=entry.target_package,
            version_code=entry.source.version_code,
        )

    def _queue_updated(self) -> None:
        self.queueChanged.emit()
        self._set_status(
            "Ready to build or install the queue."
            if self._model.rowCount()
            else "Add several APKs or game folders to begin."
        )

    def _set_status(self, message: str, progress: float | None = None) -> None:
        self._status = message
        if progress is not None:
            self._progress = min(1.0, max(0.0, progress))
        self.statusChanged.emit()

    def _operation_available(self) -> bool:
        if self.has_active_work() or self._external_busy():
            self._set_status("Wait for the current dashboard job to finish.")
            return False
        return True

    @staticmethod
    def _path_from_url(value: object) -> Path | None:
        url = value if isinstance(value, QUrl) else QUrl(str(value))
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        return Path(local).expanduser().resolve() if local else None

    @staticmethod
    def _unique_output(preferred: Path) -> Path:
        if not preferred.exists():
            return preferred
        number = 2
        while True:
            candidate = preferred.parent / f"{preferred.name} {number}"
            if not candidate.exists():
                return candidate
            number += 1
