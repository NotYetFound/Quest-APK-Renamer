"""Secure download and repair of the pinned APK build JARs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.toolchain import (
    ToolArtifact,
    load_tool_catalog,
    sha256_file,
)

if TYPE_CHECKING:
    from urllib.request import Request

ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str], None]


class DownloadResponse(Protocol):
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes: ...
    def close(self) -> None: ...


DownloadOpener = Callable[["Request", float], DownloadResponse]


class ToolRepairError(RuntimeError):
    """Raised when a pinned tool cannot be downloaded or verified safely."""


@dataclass(frozen=True, slots=True)
class ToolFileState:
    key: str
    label: str
    version: str
    status: str
    detail: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class ToolSnapshot:
    tools: tuple[ToolFileState, ...]

    @property
    def all_ready(self) -> bool:
        return all(tool.status == "ready" for tool in self.tools)


@dataclass(frozen=True, slots=True)
class ToolRepairResult:
    snapshot: ToolSnapshot
    repaired: tuple[str, ...]


def _default_open(request: Request, timeout: float) -> DownloadResponse:
    from quest_renamer.infrastructure.trusted_https import trusted_urlopen

    return cast(DownloadResponse, trusted_urlopen(request, timeout))


class PinnedToolManager:
    """Inspect and repair only artifacts explicitly pinned by the app catalog."""

    _LABELS: ClassVar[dict[str, str]] = {
        "apktool": "Apktool",
        "uber_apk_signer": "APK signer",
        "older_firmware_patch": "Older-firmware patch",
    }

    def __init__(
        self,
        *,
        catalog_path: Path,
        resource_root: Path,
        data_root: Path,
        environment: Mapping[str, str] | None = None,
        opener: DownloadOpener | None = None,
    ) -> None:
        self._catalog_path = catalog_path
        self._resource_root = resource_root
        self._data_root = data_root
        self._environment = environment if environment is not None else os.environ
        self._opener = opener or _default_open

    @property
    def managed_root(self) -> Path:
        return self._data_root / "tools"

    def _catalog(self) -> dict[str, ToolArtifact]:
        return load_tool_catalog(self._catalog_path)

    def _roots(self) -> tuple[Path, ...]:
        roots: list[Path] = []
        if override := self._environment.get("QAR_TOOLS_DIR"):
            roots.append(Path(override).expanduser())
        roots.extend((self._resource_root / "tools", self.managed_root))
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            normalized = os.path.normcase(str(root))
            if normalized not in seen:
                seen.add(normalized)
                unique.append(root)
        return tuple(unique)

    @staticmethod
    def _matches(path: Path, artifact: ToolArtifact) -> bool:
        if not path.is_file():
            return False
        try:
            return sha256_file(path) == artifact.sha256
        except OSError:
            return False

    def inspect(self) -> ToolSnapshot:
        states: list[ToolFileState] = []
        for key, artifact in self._catalog().items():
            valid: Path | None = None
            invalid = False
            for root in self._roots():
                candidate = root / artifact.file_name
                if not candidate.is_file():
                    continue
                if self._matches(candidate, artifact):
                    valid = candidate.resolve()
                    break
                invalid = True
            if valid is not None:
                status = "ready"
                detail = "Ready and verified"
            elif invalid:
                status = "damaged"
                detail = "File failed its integrity check"
            else:
                status = "missing"
                detail = "Not installed"
            states.append(
                ToolFileState(
                    key=key,
                    label=self._LABELS.get(key, key.replace("_", " ").title()),
                    version=artifact.version,
                    status=status,
                    detail=detail,
                    path=valid,
                )
            )
        return ToolSnapshot(tuple(states))

    def repair_all(
        self,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> ToolRepairResult:
        token = token or CancellationToken()
        progress = progress or (lambda _value, _message: None)
        log = log or (lambda _message: None)
        catalog = self._catalog()
        initial = self.inspect()
        pending = [state for state in initial.tools if state.status != "ready"]
        if not pending:
            progress(1.0, "Android tools are ready")
            return ToolRepairResult(initial, ())

        self.managed_root.mkdir(parents=True, exist_ok=True)
        repaired: list[str] = []
        for index, state in enumerate(pending):
            token.raise_if_cancelled()
            artifact = catalog[state.key]
            label = f"{state.label} {state.version}"
            log(f"Downloading pinned {label}.")
            destination = self.managed_root / artifact.file_name

            def item_progress(value: float, message: str, base_index: int = index) -> None:
                progress((base_index + value) / len(pending), message)

            self._download(
                artifact,
                destination,
                token=token,
                progress=item_progress,
                label=label,
            )
            repaired.append(state.key)
            log(f"Verified and installed {label}.")

        token.raise_if_cancelled()
        self._write_versions(catalog)
        snapshot = self.inspect()
        if not snapshot.all_ready:
            raise ToolRepairError("Android tools were downloaded but did not verify afterward.")
        progress(1.0, "Android tools are ready")
        return ToolRepairResult(snapshot, tuple(repaired))

    def _download(
        self,
        artifact: ToolArtifact,
        destination: Path,
        *,
        token: CancellationToken,
        progress: ProgressCallback,
        label: str,
    ) -> None:
        from urllib.request import Request

        request = Request(
            artifact.url,
            headers={"User-Agent": "Quest-APK-Renamer tool-repair"},
        )
        temporary_path: Path | None = None
        try:
            with closing(self._opener(request, 30.0)) as response:
                total_text = response.headers.get("Content-Length", "")
                total = int(total_text) if total_text.isdigit() else 0
                digest = hashlib.sha256()
                received = 0
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{destination.name}.",
                    suffix=".download",
                    dir=destination.parent,
                    delete=False,
                ) as handle:
                    temporary_path = Path(handle.name)
                    while True:
                        token.raise_if_cancelled()
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        fraction = received / total if total else 0.5
                        progress(min(fraction, 0.99), f"Downloading {label}")
                    handle.flush()
                    os.fsync(handle.fileno())
            token.raise_if_cancelled()
            if digest.hexdigest() != artifact.sha256:
                raise ToolRepairError(
                    f"{label} did not match its pinned SHA-256 checksum. "
                    "The downloaded file was discarded."
                )
            assert temporary_path is not None
            os.replace(temporary_path, destination)
            temporary_path = None
        except ToolRepairError:
            raise
        except OSError as exc:
            raise ToolRepairError(f"Could not download {label}: {exc}") from exc
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()

    def _write_versions(self, catalog: Mapping[str, ToolArtifact]) -> None:
        payload = {
            key: {
                "version": artifact.version,
                "file": artifact.file_name,
                "sha256": artifact.sha256,
            }
            for key, artifact in catalog.items()
        }
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".versions.",
                suffix=".json",
                dir=self.managed_root,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.managed_root / "versions.json")
            temporary_path = None
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()
