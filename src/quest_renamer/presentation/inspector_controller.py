"""QML-facing state for the detailed, opt-in APK Inspector workflow."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from quest_renamer.domain.inspection import DetailedApkAnalysis
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure.detailed_apk_inspector import write_analysis_report
from quest_renamer.services.contracts import DetailedInspector


@dataclass(frozen=True, slots=True)
class InspectionOutcome:
    result: DetailedApkAnalysis | None = None
    error: str = ""
    cancelled: bool = False


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1000 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1000
    return f"{value} B"


def _reported(value: object) -> str:
    if value is None or value == "":
        return "Not reported"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


class InspectorController(QObject):
    changed = Signal()
    busyChanged = Signal()
    progressReady = Signal(int, float, str)
    outcomeReady = Signal(int, object)
    activityMessage = Signal(str)

    def __init__(
        self,
        inspector: DetailedInspector,
        *,
        external_busy: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._inspector = inspector
        self._external_busy = external_busy or (lambda: False)
        self._analysis: DetailedApkAnalysis | None = None
        self._apk: Path | None = None
        self._busy = False
        self._progress = 0.0
        self._status = "Choose an APK or use the game selected on the Dashboard."
        self._tone = "neutral"
        self._token: CancellationToken | None = None
        self._generation = 0
        self.progressReady.connect(self._apply_progress)
        self.outcomeReady.connect(self._apply_outcome)

    def set_external_busy_provider(self, provider: Callable[[], bool]) -> None:
        self._external_busy = provider

    def has_active_work(self) -> bool:
        return self._busy

    @Property(bool, notify=busyChanged)
    def isBusy(self) -> bool:
        return self._busy

    @Property(bool, notify=changed)
    def hasAnalysis(self) -> bool:
        return self._analysis is not None

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
    def apkPath(self) -> str:
        return str(self._apk) if self._apk else ""

    @Property(str, notify=changed)
    def title(self) -> str:
        if self._analysis is None:
            return self._apk.name if self._apk else "No APK selected"
        return self._analysis.app_label or self._analysis.apk.name

    @Property(str, notify=changed)
    def packageName(self) -> str:
        return self._analysis.package_name if self._analysis else ""

    @Property(str, notify=changed)
    def signerLabel(self) -> str:
        if self._analysis is None:
            return ""
        signature = self._analysis.signature
        if signature.identity:
            return signature.identity.label
        return "Signed" if signature.signed else "Unsigned"

    @Property(str, notify=changed)
    def signerTone(self) -> str:
        if self._analysis is None:
            return "neutral"
        if self._analysis.signature.verified:
            return "success"
        return "warning" if self._analysis.signature.signed else "neutral"

    @Property(str, notify=changed)
    def summary(self) -> str:
        if self._analysis is None:
            return ""
        result = self._analysis
        return (
            f"Target SDK {result.target_sdk or '?'}  •  "
            f"{len(result.abis)} architecture{'s' if len(result.abis) != 1 else ''}  •  "
            f"{len(result.permissions)} permission"
            f"{'s' if len(result.permissions) != 1 else ''}  •  "
            f"{len(result.signature.certificates)} certificate"
            f"{'s' if len(result.signature.certificates) != 1 else ''}"
        )

    @Property(str, notify=changed)
    def exportFileName(self) -> str:
        package = self._analysis.package_name if self._analysis else "apk"
        return f"{package}-analysis.json"

    @Property(list, notify=changed)
    def overviewRows(self) -> list[dict[str, str]]:
        result = self._analysis
        if result is None:
            return []
        components = ", ".join(f"{name}: {count}" for name, count in result.components)
        return [
            {"label": "APK file", "value": result.apk.name},
            {"label": "File size", "value": _format_bytes(result.file_size)},
            {
                "label": "Version",
                "value": f"{result.version_name or 'Not reported'} "
                f"(code {result.version_code or 'unknown'})",
            },
            {
                "label": "Android SDK",
                "value": f"minimum {result.min_sdk or '?'} • target "
                f"{result.target_sdk or '?'} • compiled {result.compile_sdk or '?'}",
            },
            {"label": "OpenGL ES", "value": _reported(result.gl_es_version)},
            {
                "label": "CPU architectures",
                "value": ", ".join(result.abis) or "None detected",
            },
            {
                "label": "Locales",
                "value": ", ".join(result.locales) or "Default resources only",
            },
            {
                "label": "APK structure",
                "value": f"{result.dex_files} DEX • {result.native_libraries} native "
                f"libraries • {result.zip_entries} ZIP entries",
            },
            {"label": "Components", "value": components},
            {"label": "Debuggable build", "value": _reported(result.debuggable)},
            {
                "label": "Extract native libraries",
                "value": _reported(result.extract_native_libs),
            },
        ]

    @Property(list, notify=changed)
    def hashRows(self) -> list[dict[str, str]]:
        return (
            [{"label": name.upper(), "value": digest} for name, digest in self._analysis.hashes]
            if self._analysis
            else []
        )

    @Property(list, notify=changed)
    def signingRows(self) -> list[dict[str, str]]:
        if self._analysis is None:
            return []
        signature = self._analysis.signature
        certificate = signature.certificates[0] if signature.certificates else None
        identity = signature.identity
        certificates = "\n".join(
            f"#{index}: {item.subject or 'Subject unavailable'}"
            + (f" • SHA-256 {item.sha256}" if item.sha256 else "")
            for index, item in enumerate(signature.certificates, start=1)
        )
        return [
            {
                "label": "Signature status",
                "value": "Verified" if signature.verified else "Not verified",
            },
            {
                "label": "Recognized signer",
                "value": _reported(identity.full_name if identity else ""),
            },
            {
                "label": "Embedded signer lineage",
                "value": signature.lineage or "No embedded lineage",
            },
            {
                "label": "Signature schemes",
                "value": ", ".join(name.upper() for name in signature.schemes)
                or "None detected",
            },
            {
                "label": "Certificate subject",
                "value": _reported(certificate.subject if certificate else ""),
            },
            {
                "label": "Certificate issuer",
                "value": _reported(certificate.issuer if certificate else ""),
            },
            {
                "label": "Certificate SHA-256",
                "value": _reported(certificate.sha256 if certificate else ""),
            },
            {
                "label": "Certificate SHA-1",
                "value": _reported(certificate.sha1 if certificate else ""),
            },
            {"label": "Signer count", "value": str(len(signature.certificates))},
            {"label": "All certificates", "value": certificates or "None reported"},
            {
                "label": "Inspection note",
                "value": signature.error
                or "Source certificate details are retained in the exported report.",
            },
        ]

    @Property(list, notify=changed)
    def permissionRows(self) -> list[dict[str, str]]:
        if self._analysis is None:
            return []
        rows = [
            {"kind": "Permission", "name": permission, "required": "—"}
            for permission in self._analysis.permissions
        ]
        rows.extend(
            {
                "kind": "Feature",
                "name": feature.name,
                "required": "Yes" if feature.required else "No",
            }
            for feature in self._analysis.features
        )
        return rows

    @Property(list, notify=changed)
    def referenceRows(self) -> list[dict[str, Any]]:
        if self._analysis is None:
            return []
        preview = self._analysis.references
        rows: list[dict[str, Any]] = [
            {"action": "Update", "path": item.path, "count": item.occurrences}
            for item in preview.technical_files
        ]
        rows.extend(
            {"action": "Preserve", "path": item.path, "count": item.occurrences}
            for item in preview.preserved_files
        )
        return rows

    @Property(str, notify=changed)
    def referenceSummary(self) -> str:
        if self._analysis is None:
            return ""
        preview = self._analysis.references
        return (
            f"{preview.technical_occurrences} technical references across "
            f"{len(preview.technical_files)} files will be updated during a rename."
        )

    @Property(str, notify=changed)
    def nativeWarning(self) -> str:
        if self._analysis is None or not self._analysis.references.native_warnings:
            return ""
        return (
            "The old ID also appears in compiled or native data. Those bytes are reported "
            "but preserved because rewriting them may corrupt the game."
        )

    @Slot(QUrl)
    def inspectApk(self, url: QUrl) -> None:
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        self.inspectPath(local)

    @Slot(str)
    def inspectPath(self, value: str) -> None:
        if self._busy or self._external_busy():
            return
        apk = Path(value).expanduser()
        if not apk.is_file() or apk.suffix.lower() != ".apk":
            self._status = "Choose an existing APK file."
            self._tone = "error"
            self.changed.emit()
            return
        self._generation += 1
        generation = self._generation
        self._apk = apk.resolve()
        self._analysis = None
        self._token = CancellationToken()
        self._busy = True
        self._progress = 0.0
        self._status = "Preparing the APK Inspector…"
        self._tone = "neutral"
        self.changed.emit()
        self.busyChanged.emit()
        self.activityMessage.emit(f"APK Inspector started: {self._apk}")
        threading.Thread(
            target=self._worker,
            args=(generation, self._apk, self._token),
            daemon=True,
        ).start()

    def _worker(self, generation: int, apk: Path, token: CancellationToken) -> None:
        try:
            result = self._inspector.inspect(
                apk,
                token=token,
                progress=lambda value, message: self.progressReady.emit(
                    generation, value, message
                ),
                log=lambda message: self.activityMessage.emit(f"APK Inspector: {message}"),
            )
            outcome = InspectionOutcome(result=result)
        except OperationCancelled:
            outcome = InspectionOutcome(cancelled=True)
        except Exception as exc:
            outcome = InspectionOutcome(error=str(exc))
        self.outcomeReady.emit(generation, outcome)

    @Slot()
    def cancel(self) -> None:
        if self._token is not None:
            self._token.cancel()
            self._status = "Stopping inspection safely…"
            self._tone = "warning"
            self.changed.emit()

    @Slot(int, float, str)
    def _apply_progress(self, generation: int, value: float, message: str) -> None:
        if generation != self._generation:
            return
        self._progress = min(1.0, max(0.0, value))
        self._status = message
        self.changed.emit()

    @Slot(int, object)
    def _apply_outcome(self, generation: int, raw_outcome: object) -> None:
        if generation != self._generation or not isinstance(raw_outcome, InspectionOutcome):
            return
        self._busy = False
        self._token = None
        if raw_outcome.cancelled:
            self._status = "Inspection cancelled. No files were changed."
            self._tone = "warning"
            self.activityMessage.emit("APK Inspector cancelled safely.")
        elif raw_outcome.result is None:
            self._status = raw_outcome.error or "The APK could not be inspected."
            self._tone = "error"
            self.activityMessage.emit(f"APK Inspector failed: {self._status}")
        else:
            self._analysis = raw_outcome.result
            self._status = "Inspection complete. Nothing in the APK was changed."
            self._tone = "success"
            self.activityMessage.emit(f"APK Inspector complete: {self._analysis.package_name}")
        self.changed.emit()
        self.busyChanged.emit()

    @Slot(QUrl)
    def exportAnalysis(self, url: QUrl) -> None:
        if self._analysis is None or self._busy:
            return
        local = url.toLocalFile() if url.isLocalFile() else url.toString()
        if not local:
            return
        destination = Path(local)
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        try:
            write_analysis_report(destination, self._analysis)
        except OSError as exc:
            self._status = f"The analysis report could not be exported: {exc}"
            self._tone = "error"
            self.activityMessage.emit(self._status)
        else:
            self._status = f"Analysis exported to {destination.name}."
            self._tone = "success"
            self.activityMessage.emit(f"APK analysis exported: {destination}")
        self.changed.emit()
