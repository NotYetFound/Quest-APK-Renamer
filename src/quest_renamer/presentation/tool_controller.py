"""QML-facing state for pinned Android tool inspection and repair."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Property, QObject, Signal, Slot

from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure.tool_manager import (
    PinnedToolManager,
    ToolRepairResult,
    ToolSnapshot,
)


@dataclass(frozen=True, slots=True)
class ToolRepairOutcome:
    result: ToolRepairResult | None = None
    error: str = ""
    cancelled: bool = False


class ToolController(QObject):
    changed = Signal()
    # Emitted only when the tool snapshot itself changes, so QML row lists are not
    # rebuilt on every progress tick.
    snapshotChanged = Signal()
    busyChanged = Signal()
    progressReady = Signal(float, str)
    outcomeReady = Signal(object)
    activityMessage = Signal(str)

    def __init__(
        self,
        manager: PinnedToolManager,
        *,
        activate_tools: Callable[[], None] | None = None,
        external_busy: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._activate_tools = activate_tools or (lambda: None)
        self._external_busy = external_busy or (lambda: False)
        self._snapshot = manager.inspect()
        self._busy = False
        self._progress = 0.0
        self._status = self._summary(self._snapshot)
        self._tone = "success" if self._snapshot.all_ready else "warning"
        self._token: CancellationToken | None = None
        self.progressReady.connect(self._apply_progress)
        self.outcomeReady.connect(self._apply_outcome)

    def set_external_busy_provider(self, provider: Callable[[], bool]) -> None:
        self._external_busy = provider

    def has_active_work(self) -> bool:
        return self._busy

    @staticmethod
    def _summary(snapshot: ToolSnapshot) -> str:
        if snapshot.all_ready:
            return "Pinned Android tools are ready."
        missing = sum(tool.status == "missing" for tool in snapshot.tools)
        damaged = sum(tool.status == "damaged" for tool in snapshot.tools)
        parts: list[str] = []
        if missing:
            parts.append(f"{missing} missing")
        if damaged:
            parts.append(f"{damaged} damaged")
        return "Android tools need attention: " + ", ".join(parts) + "."

    @Property(bool, notify=busyChanged)
    def isBusy(self) -> bool:
        return self._busy

    @Property(bool, notify=snapshotChanged)
    def allReady(self) -> bool:
        return self._snapshot.all_ready

    @Property(float, notify=changed)
    def progress(self) -> float:
        return self._progress

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(str, notify=changed)
    def tone(self) -> str:
        return self._tone

    @Property(str, notify=changed)
    def actionLabel(self) -> str:
        if self._busy:
            return "Cancel"
        return "Verify again" if self._snapshot.all_ready else "Repair tools"

    @Property(list, notify=snapshotChanged)
    def toolRows(self) -> list[dict[str, str]]:
        return [
            {
                "key": tool.key,
                "label": tool.label,
                "version": tool.version,
                "status": tool.status,
                "detail": tool.detail,
            }
            for tool in self._snapshot.tools
        ]

    @Slot()
    def runAction(self) -> None:
        if self._busy:
            self.cancel()
        else:
            self.repair()

    @Slot()
    def repair(self) -> None:
        if self._busy:
            return
        if self._external_busy():
            self._status = "Wait for the current operation to finish first."
            self._tone = "warning"
            self.changed.emit()
            return
        self._busy = True
        self._progress = 0.0
        self._status = "Checking pinned Android tools…"
        self._tone = "neutral"
        self._token = CancellationToken()
        self.changed.emit()
        self.busyChanged.emit()
        self.activityMessage.emit("Android tool verification started.")
        threading.Thread(target=self._repair_worker, args=(self._token,), daemon=True).start()

    @Slot()
    def cancel(self) -> None:
        if self._token is None:
            return
        self._token.cancel()
        self._status = "Stopping safely after the current read…"
        self.changed.emit()

    def _repair_worker(self, token: CancellationToken) -> None:
        try:
            result = self._manager.repair_all(
                token=token,
                progress=lambda value, message: self.progressReady.emit(value, message),
                log=self.activityMessage.emit,
            )
            outcome = ToolRepairOutcome(result=result)
        except OperationCancelled:
            outcome = ToolRepairOutcome(cancelled=True)
        except Exception as exc:  # any failure must release the busy flag
            outcome = ToolRepairOutcome(error=str(exc))
        self.outcomeReady.emit(outcome)

    @Slot(float, str)
    def _apply_progress(self, value: float, message: str) -> None:
        self._progress = min(max(value, 0.0), 1.0)
        self._status = message
        self.changed.emit()

    @Slot(object)
    def _apply_outcome(self, raw_outcome: object) -> None:
        if not isinstance(raw_outcome, ToolRepairOutcome):
            return
        self._token = None
        self._busy = False
        try:
            self._snapshot = self._manager.inspect()
            self.snapshotChanged.emit()
        except (OSError, ValueError) as exc:
            self._status = f"Tool status could not be read: {exc}"
            self._tone = "error"
        else:
            if raw_outcome.cancelled:
                self._status = "Tool repair cancelled. Existing files were kept."
                self._tone = "warning"
                self.activityMessage.emit("Android tool repair cancelled safely.")
            elif raw_outcome.error:
                self._status = raw_outcome.error
                self._tone = "error"
                self.activityMessage.emit(f"Android tool repair failed: {raw_outcome.error}")
            else:
                try:
                    self._activate_tools()
                except (OSError, ValueError) as exc:
                    self._status = f"Tools were repaired but could not be activated: {exc}"
                    self._tone = "error"
                    self.activityMessage.emit(self._status)
                else:
                    self._progress = 1.0
                    self._status = self._summary(self._snapshot)
                    self._tone = "success" if self._snapshot.all_ready else "warning"
                    repaired = len(raw_outcome.result.repaired) if raw_outcome.result else 0
                    message = (
                        f"Android tools repaired ({repaired} file"
                        f"{'s' if repaired != 1 else ''})."
                        if repaired
                        else "Android tools verified."
                    )
                    self.activityMessage.emit(message)
        self.changed.emit()
        self.busyChanged.emit()

    @Slot()
    def refreshExternalBusy(self) -> None:
        self.busyChanged.emit()
