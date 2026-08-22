"""Reliable native, Qt-rendered, and legacy file-dialog fallback chain."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from quest_renamer.infrastructure.legacy_file_picker import (
    LegacyPickerResult,
    PickerKind,
    legacy_fallback_pick,
    linux_desktop_pick,
)

DialogFactory = Callable[[], QFileDialog]
Picker = Callable[[PickerKind, str, Path, str], LegacyPickerResult | None]
AttemptState = Literal["selected", "cancelled", "failed"]


@dataclass(frozen=True, slots=True)
class DialogAttempt:
    state: AttemptState
    paths: tuple[Path, ...] = ()
    error: str = ""


def existing_dialog_directory(value: str) -> Path:
    """Return a real directory even when a remembered path was removed."""
    candidate = Path(value).expanduser() if value.strip() else Path.home()
    if candidate.is_file():
        candidate = candidate.parent
    while not candidate.is_dir() and candidate != candidate.parent:
        candidate = candidate.parent
    if candidate.is_dir():
        return candidate.resolve()
    home = Path.home()
    return home.resolve() if home.is_dir() else Path.cwd().resolve()


class FileDialogController(QObject):
    """Prefer native dialogs while remaining independent of desktop integration."""

    folderSelected = Signal(str, QUrl)
    fileSelected = Signal(str, QUrl)
    filesSelected = Signal(str, list)
    saveSelected = Signal(str, QUrl)
    selectionCancelled = Signal(str)
    dialogFailed = Signal(str)

    def __init__(
        self,
        *,
        dialog_factory: DialogFactory | None = None,
        desktop_picker: Picker | None = None,
        legacy_picker: Picker | None = None,
        clock: Callable[[], float] | None = None,
        platform_name: str = sys.platform,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._dialog_factory = dialog_factory or QFileDialog
        self._desktop_picker = desktop_picker or linux_desktop_pick
        self._legacy_picker = legacy_picker or legacy_fallback_pick
        self._clock = clock or time.monotonic
        self._platform_name = platform_name

    def _dialog(
        self,
        kind: PickerKind,
        title: str,
        initial: Path,
        suggested_name: str,
        *,
        native: bool,
    ) -> QFileDialog:
        dialog = self._dialog_factory()
        dialog.setWindowTitle(title)
        dialog.setDirectory(str(initial))
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, not native)
        if kind == "folder":
            dialog.setFileMode(QFileDialog.FileMode.Directory)
            dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        elif kind == "apks":
            dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
            dialog.setNameFilters(["Android packages (*.apk)", "All files (*)"])
        elif kind == "archive":
            dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
            dialog.setNameFilters(
                ["Quest APK Renamer Library (*.qarlib)", "All files (*)"]
            )
        elif kind in {"save_archive", "save_json", "save_log"}:
            is_archive = kind == "save_archive"
            is_json = kind == "save_json"
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dialog.setFileMode(QFileDialog.FileMode.AnyFile)
            dialog.setNameFilters(
                [
                    "Quest APK Renamer Library (*.qarlib)"
                    if is_archive
                    else "JSON report (*.json)"
                    if is_json
                    else "Log files (*.log)",
                    "All files (*)",
                ]
            )
            dialog.setDefaultSuffix(
                "qarlib" if is_archive else "json" if is_json else "log"
            )
            dialog.selectFile(suggested_name)
        else:
            dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
            dialog.setNameFilters(["Android packages (*.apk)", "All files (*)"])
        return dialog

    def _try_qt(
        self,
        kind: PickerKind,
        title: str,
        initial: Path,
        suggested_name: str,
        *,
        native: bool,
    ) -> DialogAttempt:
        started = self._clock()
        try:
            dialog = self._dialog(
                kind,
                title,
                initial,
                suggested_name,
                native=native,
            )
            result = dialog.exec()
            paths = tuple(Path(path) for path in dialog.selectedFiles())
        except (OSError, RuntimeError) as exc:
            return DialogAttempt("failed", error=str(exc))
        elapsed = self._clock() - started
        if result == QFileDialog.DialogCode.Accepted and paths:
            return DialogAttempt("selected", paths)
        if result == QFileDialog.DialogCode.Accepted:
            return DialogAttempt("failed", error="The picker returned no path.")
        # Broken portal/platform plugins normally reject immediately without ever
        # presenting UI. A user-visible cancellation takes longer than this.
        if elapsed < 0.2:
            backend = "native" if native else "Qt"
            return DialogAttempt("failed", error=f"The {backend} picker did not open.")
        return DialogAttempt("cancelled")

    def _pick(
        self,
        kind: PickerKind,
        title: str,
        initial: str,
        suggested_name: str = "",
    ) -> tuple[Path, ...]:
        start = existing_dialog_directory(initial)
        errors: list[str] = []
        if self._platform_name.startswith("linux"):
            desktop_result = self._desktop_picker(kind, title, start, suggested_name)
            if desktop_result is not None:
                if desktop_result.paths:
                    return desktop_result.paths
                if desktop_result.cancelled:
                    return ()
                errors.extend(desktop_result.errors)
        for native in (True, False):
            attempt = self._try_qt(
                kind,
                title,
                start,
                suggested_name,
                native=native,
            )
            if attempt.state == "selected":
                return attempt.paths
            if attempt.state == "cancelled":
                return ()
            if attempt.error:
                errors.append(attempt.error)

        raw_result = self._legacy_picker(kind, title, start, suggested_name)
        paths = tuple(getattr(raw_result, "paths", ()))
        if paths:
            return paths
        if bool(getattr(raw_result, "cancelled", False)):
            return ()
        errors.extend(str(value) for value in getattr(raw_result, "errors", ()))
        detail = "\n".join(errors) or "No compatible picker backend is available."
        self.dialogFailed.emit(
            "No file picker could open. You can still paste a path or drag files onto the app."
            f"\n\n{detail}"
        )
        return ()

    @Slot(str, str, str)
    def chooseFolder(self, purpose: str, title: str, initial: str = "") -> None:
        paths = self._pick("folder", title, initial)
        if paths:
            self.folderSelected.emit(purpose, QUrl.fromLocalFile(str(paths[0])))
        else:
            self.selectionCancelled.emit(purpose)

    @Slot(str, str, str)
    def chooseApk(self, purpose: str, title: str, initial: str = "") -> None:
        paths = self._pick("apk", title, initial)
        if paths:
            self.fileSelected.emit(purpose, QUrl.fromLocalFile(str(paths[0])))
        else:
            self.selectionCancelled.emit(purpose)

    @Slot(str, str, str)
    def chooseApks(self, purpose: str, title: str, initial: str = "") -> None:
        paths = self._pick("apks", title, initial)
        if paths:
            self.filesSelected.emit(
                purpose,
                [QUrl.fromLocalFile(str(path)) for path in paths],
            )
        else:
            self.selectionCancelled.emit(purpose)

    @Slot(str, str, str)
    def chooseLibraryArchive(self, purpose: str, title: str, initial: str = "") -> None:
        paths = self._pick("archive", title, initial)
        if paths:
            self.fileSelected.emit(purpose, QUrl.fromLocalFile(str(paths[0])))
        else:
            self.selectionCancelled.emit(purpose)

    @Slot(str, str, str, str)
    def saveLibraryArchive(
        self,
        purpose: str,
        title: str,
        suggested_name: str,
        initial: str = "",
    ) -> None:
        paths = self._pick("save_archive", title, initial, suggested_name)
        if paths:
            self.saveSelected.emit(purpose, QUrl.fromLocalFile(str(paths[0])))

    @Slot(str, str, str, str)
    def saveJson(
        self,
        purpose: str,
        title: str,
        suggested_name: str,
        initial: str = "",
    ) -> None:
        paths = self._pick("save_json", title, initial, suggested_name)
        if paths:
            self.saveSelected.emit(purpose, QUrl.fromLocalFile(str(paths[0])))

    @Slot(str, str, str, str)
    def saveLog(
        self,
        purpose: str,
        title: str,
        suggested_name: str,
        initial: str = "",
    ) -> None:
        paths = self._pick("save_log", title, initial, suggested_name)
        if paths:
            self.saveSelected.emit(purpose, QUrl.fromLocalFile(str(paths[0])))
