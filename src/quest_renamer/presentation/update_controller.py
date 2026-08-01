"""Non-blocking update-check state for QML."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from quest_renamer.domain.releases import ReleaseCheckResult
from quest_renamer.infrastructure.github_releases import GitHubReleaseChecker


@dataclass(frozen=True, slots=True)
class UpdateOutcome:
    result: ReleaseCheckResult | None = None
    error: str = ""


class UpdateController(QObject):
    changed = Signal()
    busyChanged = Signal()
    outcomeReady = Signal(object)
    activityMessage = Signal(str)

    def __init__(
        self,
        checker: GitHubReleaseChecker,
        *,
        current_version: str,
        preferences: Callable[[], tuple[bool, str]],
        save_dismissal: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._checker = checker
        self._current_version = current_version
        self._preferences = preferences
        self._save_dismissal = save_dismissal
        self._busy = False
        self._manual_requested = False
        self._checked = False
        self._result: ReleaseCheckResult | None = None
        self._banner_visible = False
        self._status = "Updates are checked quietly in the background."
        self._tone = "neutral"
        self.outcomeReady.connect(self._apply_outcome)

    @Property(bool, notify=busyChanged)
    def isBusy(self) -> bool:
        return self._busy

    @Property(bool, notify=changed)
    def bannerVisible(self) -> bool:
        return self._banner_visible

    @Property(bool, notify=changed)
    def hasUpdate(self) -> bool:
        return self._result is not None and self._result.has_update

    @Property(str, notify=changed)
    def latestVersion(self) -> str:
        if self._result is None or self._result.latest is None:
            return ""
        return self._result.latest.tag

    @Property(str, notify=changed)
    def releaseName(self) -> str:
        if self._result is None or self._result.latest is None:
            return ""
        return self._result.latest.name

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(str, notify=changed)
    def tone(self) -> str:
        return self._tone

    @Property(str, constant=True)
    def currentVersion(self) -> str:
        return self._current_version

    @Slot()
    def startAutomatic(self) -> None:
        enabled, _dismissed = self._preferences()
        if enabled and not self._checked:
            self._start(manual=False)
        elif not enabled:
            self._status = "Automatic update checks are off."
            self._tone = "neutral"
            self.changed.emit()

    @Slot()
    def checkNow(self) -> None:
        self._start(manual=True)

    def _start(self, *, manual: bool) -> None:
        self._manual_requested = self._manual_requested or manual
        if self._busy:
            return
        self._busy = True
        self._status = "Checking GitHub for updates…"
        self._tone = "neutral"
        self.changed.emit()
        self.busyChanged.emit()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            outcome = UpdateOutcome(result=self._checker.check())
        except (OSError, ValueError) as exc:
            outcome = UpdateOutcome(error=str(exc))
        self.outcomeReady.emit(outcome)

    @Slot(object)
    def _apply_outcome(self, raw_outcome: object) -> None:
        if not isinstance(raw_outcome, UpdateOutcome):
            return
        manual = self._manual_requested
        self._manual_requested = False
        self._busy = False
        self._checked = True
        if raw_outcome.error:
            self._status = "GitHub could not be reached. Try again later."
            self._tone = "warning" if manual else "neutral"
            self.activityMessage.emit(f"Update check failed: {raw_outcome.error}")
        else:
            self._result = raw_outcome.result
            latest = self._result.latest if self._result else None
            if latest is None:
                self._status = "No compatible releases have been published yet."
                self._tone = "neutral"
                self.activityMessage.emit("Update check: no compatible release found.")
            elif self._result and self._result.has_update:
                _enabled, dismissed = self._preferences()
                self._banner_visible = manual or dismissed != latest.tag
                self._status = f"Update available: {latest.tag}"
                self._tone = "success"
                self.activityMessage.emit(f"Update available: {latest.tag}.")
            else:
                self._banner_visible = False
                self._status = f"You're up to date — v{self._current_version}."
                self._tone = "success"
                self.activityMessage.emit("Update check: this version is current.")
        self.changed.emit()
        self.busyChanged.emit()

    @Slot()
    def openRelease(self) -> None:
        if self._result is None or self._result.latest is None:
            return
        url = QUrl(self._result.latest.url)
        if url.isValid() and url.scheme() == "https":
            QDesktopServices.openUrl(url)

    @Slot()
    def dismiss(self) -> None:
        if self._result is not None and self._result.latest is not None:
            self._save_dismissal(self._result.latest.tag)
        self._banner_visible = False
        self.changed.emit()

    @Slot()
    def refreshPreference(self) -> None:
        enabled, _dismissed = self._preferences()
        if not enabled and not self._busy:
            self._status = "Automatic update checks are off."
            self._tone = "neutral"
            self.changed.emit()
