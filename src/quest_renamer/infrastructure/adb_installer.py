"""Cancellable, verified installation on one authorized Quest."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.installation import (
    BundleInstallError,
    BundleInstallResult,
    InstalledObb,
    InstalledPackageConflict,
)
from quest_renamer.domain.models import BundleDraft
from quest_renamer.domain.obb_names import parse_obb_filename
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.domain.package_ids import is_valid_package_id
from quest_renamer.infrastructure.adb_device import find_adb
from quest_renamer.infrastructure.process_runner import ProcessRunner


@dataclass(frozen=True, slots=True)
class _RemoteObb:
    name: str
    path: str
    size: int
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class _PreparedObb:
    source: Path
    remote_path: str
    size: int
    action: str
    staged_path: str = ""
    reused_path: str = ""
    backup_path: str = ""


class AdbApkInstaller:
    _MAX_LOCAL_HASHES = 32

    def __init__(
        self,
        *,
        resource_root: Path | None = None,
        executable: Path | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.resource_root = resource_root
        self.executable = executable
        self.runner = runner or ProcessRunner()
        self._local_hashes: OrderedDict[tuple[Path, int, int], str] = OrderedDict()

    def install_bundle(
        self,
        bundle: BundleDraft,
        serial: str,
        *,
        token: CancellationToken | None = None,
        progress: Callable[[float, str], None] | None = None,
        log: Callable[[str], None] | None = None,
        allow_existing: bool = False,
    ) -> BundleInstallResult:
        token = token or CancellationToken()
        progress = progress or (lambda _value, _message: None)
        log = log or (lambda _message: None)
        target = self._validated_target(bundle, serial)

        token.raise_if_cancelled()
        progress(0.02, "Checking installed package")
        if not allow_existing and self._package_is_installed(
            bundle.package_name, target, token, log
        ):
            raise InstalledPackageConflict(bundle.package_name)
        prepared = self._prepare_obb_sync(bundle, target, token, progress, log)
        activated = False
        try:
            self._activate_prepared_obbs(prepared, target, token, log)
            activated = True
            token.raise_if_cancelled()
            progress(0.68, "Installing APK")
            apk_result = self.runner.run(
                (*target, "install", "-r", "-g", bundle.apk),
                token=token,
                log=log,
            )
            if not self._confirmed_success(apk_result.output):
                raise BundleInstallError(
                    "ADB finished without confirming a successful APK install."
                )
            progress(0.86, "APK installed • verifying package and OBB files")
            self._verify_prepared_obbs(prepared, target, token, log)
            self._verify_package(bundle.package_name, target, token, progress, log)
            self._finish_obb_sync(bundle, prepared, target, token, log)
            progress(1.0, "Install verified")
        except Exception:
            if activated:
                log("Install verification failed; restoring the previous OBB set.")
                self._rollback_prepared_obbs(prepared, target, log)
            else:
                self._remove_staged_obbs(prepared, target, log)
            raise
        installed_obbs = tuple(
            InstalledObb(item.source, item.remote_path, item.size, item.action)
            for item in prepared
        )
        return BundleInstallResult(
            bundle.package_name,
            bundle.apk,
            installed_obbs,
            True,
        )

    def retry_obbs(
        self,
        bundle: BundleDraft,
        serial: str,
        *,
        token: CancellationToken | None = None,
        progress: Callable[[float, str], None] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> BundleInstallResult:
        token = token or CancellationToken()
        progress = progress or (lambda _value, _message: None)
        log = log or (lambda _message: None)
        target = self._validated_target(bundle, serial)
        if not bundle.obbs:
            raise BundleInstallError("There are no failed OBB files to retry.")
        progress(0.04, "Preparing OBB retry")
        prepared = self._prepare_obb_sync(bundle, target, token, progress, log)
        self._activate_prepared_obbs(prepared, target, token, log)
        try:
            self._verify_prepared_obbs(prepared, target, token, log)
            self._verify_package(bundle.package_name, target, token, progress, log)
        except Exception:
            self._rollback_prepared_obbs(prepared, target, log)
            raise
        installed_obbs = tuple(
            InstalledObb(item.source, item.remote_path, item.size, item.action)
            for item in prepared
        )
        self._finish_obb_sync(bundle, prepared, target, token, log)
        progress(1.0, "OBB retry verified")
        return BundleInstallResult(
            bundle.package_name,
            bundle.apk,
            installed_obbs,
            True,
        )

    def _validated_target(self, bundle: BundleDraft, serial: str) -> tuple[Path, str, str]:
        if not bundle.apk.is_file() or bundle.apk.suffix.lower() != ".apk":
            raise BundleInstallError("The finished folder does not contain a readable APK.")
        if not is_valid_package_id(bundle.package_name):
            raise BundleInstallError("The finished folder does not contain a valid package ID.")
        for obb in bundle.obbs:
            if not obb.is_file():
                raise BundleInstallError(f"The OBB file is missing: {obb.name}")
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.obb", obb.name, re.IGNORECASE):
                raise BundleInstallError(
                    f"The OBB filename contains unsupported characters: {obb.name}"
                )
        adb = find_adb(resource_root=self.resource_root, executable=self.executable)
        if adb is None:
            raise BundleInstallError("ADB is not available.")
        if not serial:
            raise BundleInstallError("No authorized Quest is selected.")
        return (adb, "-s", serial)

    def _prepare_obb_sync(
        self,
        bundle: BundleDraft,
        target: tuple[Path, str, str],
        token: CancellationToken,
        progress: Callable[[float, str], None],
        log: Callable[[str], None],
    ) -> tuple[_PreparedObb, ...]:
        try:
            return self._prepare_obb_sync_impl(bundle, target, token, progress, log)
        except Exception:
            self._remove_transaction_staging(bundle, target, log)
            raise

    def _prepare_obb_sync_impl(
        self,
        bundle: BundleDraft,
        target: tuple[Path, str, str],
        token: CancellationToken,
        progress: Callable[[float, str], None],
        log: Callable[[str], None],
    ) -> tuple[_PreparedObb, ...]:
        remote_root = f"/sdcard/Android/obb/{bundle.package_name}"
        transaction_id = uuid.uuid4().hex[:12]
        if not bundle.obbs:
            return ()
        token.raise_if_cancelled()
        progress(0.05, "Checking existing OBB files")
        self.runner.run((*target, "shell", "mkdir", "-p", remote_root), log=log)
        self._remove_transaction_staging(bundle, target, log)
        remote = self._remote_obbs(target, remote_root, token, log)
        used_remote: set[str] = set()
        prepared: list[_PreparedObb] = []
        for index, obb in enumerate(bundle.obbs, start=1):
            token.raise_if_cancelled()
            remote_path = f"{remote_root}/{obb.name}"
            size = obb.stat().st_size
            progress(
                0.06 + ((index - 1) / len(bundle.obbs)) * 0.05,
                f"Comparing OBB {index} of {len(bundle.obbs)} • {obb.name}",
            )
            same_name = remote.get(obb.name)
            local_hash = ""
            if same_name is not None and same_name.size == size:
                local_hash = self._local_sha256(obb, token)
                remote_hash = self._remote_sha256(target, same_name.path, token, log)
                if remote_hash and remote_hash == local_hash:
                    log(f"OBB already matches on Quest; skipping transfer: {obb.name}")
                    prepared.append(_PreparedObb(obb, remote_path, size, "unchanged"))
                    used_remote.add(same_name.name)
                    continue

            reusable: _RemoteObb | None = None
            for candidate in remote.values():
                if candidate.name in used_remote or candidate.size != size:
                    continue
                if not local_hash:
                    local_hash = self._local_sha256(obb, token)
                candidate_hash = self._remote_sha256(target, candidate.path, token, log)
                if candidate_hash and candidate_hash == local_hash:
                    reusable = candidate
                    break
            if reusable is not None:
                log(
                    f"Reusing identical Quest OBB without uploading: "
                    f"{reusable.name} -> {obb.name}"
                )
                used_remote.add(reusable.name)
                prepared.append(
                    _PreparedObb(
                        obb,
                        remote_path,
                        size,
                        "renamed on Quest",
                        reused_path=reusable.path,
                        backup_path=f"{remote_path}.qar-old-{transaction_id}-{index}",
                    )
                )
                continue

            staged = f"{remote_root}/.qar-new-{transaction_id}-{index}-{obb.name}"
            progress(
                0.12 + ((index - 1) / len(bundle.obbs)) * 0.46,
                self._copy_label(index, len(bundle.obbs), obb.name, size),
            )
            try:
                self.runner.run((*target, "push", obb, staged), token=token, log=log)
                token.raise_if_cancelled()
                remote_size = self._remote_file_size(target, staged, token, log)
            except OperationCancelled:
                self._remove_remote(target, staged, log)
                raise
            except Exception as exc:
                self._remove_remote(target, staged, log)
                remaining = tuple(bundle.obbs[index - 1 :])
                raise BundleInstallError(
                    f"OBB transfer failed for {obb.name}: {exc}",
                    failed_obbs=remaining,
                ) from exc
            local_size = obb.stat().st_size
            if remote_size != local_size:
                remaining = tuple(bundle.obbs[index - 1 :])
                raise BundleInstallError(
                    f"Quest reported the wrong size for {obb.name}.",
                    failed_obbs=remaining,
                )
            prepared.append(
                _PreparedObb(
                    obb,
                    remote_path,
                    local_size,
                    "uploaded",
                    staged_path=staged,
                    backup_path=f"{remote_path}.qar-old-{transaction_id}-{index}",
                )
            )
        progress(0.62, "OBB set prepared safely")
        return tuple(prepared)

    def _remove_transaction_staging(
        self,
        bundle: BundleDraft,
        target: tuple[Path, str, str],
        log: Callable[[str], None],
    ) -> None:
        remote_root = f"/sdcard/Android/obb/{bundle.package_name}"
        result = self.runner.run(
            (*target, "shell", "ls", "-1", remote_root),
            log=log,
            check=False,
        )
        for raw in result.output:
            name = raw.strip()
            if name.startswith(".qar-new-") and re.fullmatch(
                r"\.qar-new-[0-9a-f]{12}-\d+-[A-Za-z0-9._-]+\.obb",
                name,
                re.IGNORECASE,
            ):
                self._remove_remote(target, f"{remote_root}/{name}", log)

    def _activate_prepared_obbs(
        self,
        prepared: tuple[_PreparedObb, ...],
        target: tuple[Path, str, str],
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> None:
        if not prepared:
            return
        token.raise_if_cancelled()
        self.runner.run(
            (*target, "shell", "am", "force-stop", self._package_from_remote(prepared[0])),
            log=log,
            check=False,
        )
        activated: list[_PreparedObb] = []
        try:
            for item in prepared:
                token.raise_if_cancelled()
                if item.action == "unchanged":
                    continue
                if self._remote_file_size(target, item.remote_path, token, log) is not None:
                    self.runner.run(
                        (*target, "shell", "mv", item.remote_path, item.backup_path),
                        token=token,
                        log=log,
                    )
                incoming = item.staged_path or item.reused_path
                self.runner.run(
                    (*target, "shell", "mv", incoming, item.remote_path),
                    token=token,
                    log=log,
                )
                activated.append(item)
        except Exception:
            self._rollback_prepared_obbs(tuple(activated), target, log)
            raise

    def _verify_prepared_obbs(
        self,
        prepared: tuple[_PreparedObb, ...],
        target: tuple[Path, str, str],
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> None:
        for item in prepared:
            token.raise_if_cancelled()
            if self._remote_file_size(target, item.remote_path, token, log) != item.size:
                raise BundleInstallError(
                    f"Quest reported the wrong size for {item.source.name}.",
                    failed_obbs=(item.source,),
                )

    def _finish_obb_sync(
        self,
        bundle: BundleDraft,
        prepared: tuple[_PreparedObb, ...],
        target: tuple[Path, str, str],
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> None:
        expected = {item.source.name for item in prepared}
        for item in prepared:
            token.raise_if_cancelled()
            if item.backup_path:
                self._remove_remote(target, item.backup_path, log)
        remote_root = f"/sdcard/Android/obb/{bundle.package_name}"
        remote = self._remote_obbs(target, remote_root, token, log)
        previously_managed = set(bundle.managed_obb_names)
        for remote_item in remote.values():
            parsed = parse_obb_filename(remote_item.name)
            belongs_to_package = bool(
                parsed is not None
                and parsed.package_name.casefold() == bundle.package_name.casefold()
            )
            if remote_item.name not in expected and (
                belongs_to_package or remote_item.name in previously_managed
            ):
                log(
                    f"Removing obsolete versioned OBB after verified update: {remote_item.name}"
                )
                self._remove_remote(target, remote_item.path, log)

    def _rollback_prepared_obbs(
        self,
        prepared: tuple[_PreparedObb, ...],
        target: tuple[Path, str, str],
        log: Callable[[str], None],
    ) -> None:
        for item in reversed(prepared):
            if item.action == "unchanged":
                continue
            if item.reused_path:
                self.runner.run(
                    (*target, "shell", "mv", item.remote_path, item.reused_path),
                    log=log,
                    check=False,
                )
            else:
                self._remove_remote(target, item.remote_path, log)
            self.runner.run(
                (*target, "shell", "mv", item.backup_path, item.remote_path),
                log=log,
                check=False,
            )

    def _remove_staged_obbs(
        self,
        prepared: tuple[_PreparedObb, ...],
        target: tuple[Path, str, str],
        log: Callable[[str], None],
    ) -> None:
        for item in prepared:
            if item.staged_path:
                self._remove_remote(target, item.staged_path, log)

    def _remote_obbs(
        self,
        target: tuple[Path, str, str],
        remote_root: str,
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> dict[str, _RemoteObb]:
        result = self.runner.run(
            (*target, "shell", "ls", "-1", remote_root),
            token=token,
            log=log,
            check=False,
        )
        remote: dict[str, _RemoteObb] = {}
        for raw in result.output:
            name = raw.strip()
            if name.startswith(".qar-"):
                continue
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.obb", name, re.IGNORECASE):
                continue
            path = f"{remote_root}/{name}"
            size = self._remote_file_size(target, path, token, log)
            if size is not None:
                remote[name] = _RemoteObb(name, path, size)
        return remote

    def _local_sha256(self, path: Path, token: CancellationToken) -> str:
        stat = path.stat()
        key = (path.resolve(), stat.st_size, stat.st_mtime_ns)
        cached = self._local_hashes.get(key)
        if cached is not None:
            self._local_hashes.move_to_end(key)
            return cached
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                token.raise_if_cancelled()
                digest.update(chunk)
        value = digest.hexdigest()
        self._local_hashes[key] = value
        self._local_hashes.move_to_end(key)
        while len(self._local_hashes) > self._MAX_LOCAL_HASHES:
            self._local_hashes.popitem(last=False)
        return value

    def _remote_sha256(
        self,
        target: tuple[Path, str, str],
        path: str,
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> str:
        for command in (
            (*target, "shell", "sha256sum", path),
            (*target, "shell", "toybox", "sha256sum", path),
        ):
            token.raise_if_cancelled()
            result = self.runner.run(command, log=log, check=False)
            for line in result.output:
                digest = line.strip().split(maxsplit=1)[0].lower()
                if re.fullmatch(r"[0-9a-f]{64}", digest):
                    return digest
        return ""

    @staticmethod
    def _copy_label(index: int, count: int, name: str, size: int) -> str:
        if size >= 1024**3:
            formatted = f"{size / (1024**3):.2f} GB"
        else:
            formatted = f"{size / (1024**2):.1f} MB"
        return f"Uploading changed OBB {index} of {count} • {name} • {formatted}"

    @staticmethod
    def _package_from_remote(item: _PreparedObb) -> str:
        prefix = "/sdcard/Android/obb/"
        value = item.remote_path.removeprefix(prefix)
        return value.split("/", 1)[0]

    def _remove_remote(
        self,
        target: tuple[Path, str, str],
        path: str,
        log: Callable[[str], None],
    ) -> None:
        self.runner.run(
            (*target, "shell", "rm", "-f", path),
            log=log,
            check=False,
        )

    def _verify_package(
        self,
        package_name: str,
        target: tuple[Path, str, str],
        token: CancellationToken,
        progress: Callable[[float, str], None],
        log: Callable[[str], None],
    ) -> None:
        token.raise_if_cancelled()
        progress(0.94, "Verifying installed package")
        package_result = self.runner.run(
            (*target, "shell", "pm", "path", package_name),
            log=log,
            check=False,
        )
        verified = package_result.returncode == 0 and any(
            line.strip().startswith("package:") for line in package_result.output
        )
        if not verified:
            raise BundleInstallError("The Quest did not report the package after installation.")

    def _package_is_installed(
        self,
        package_name: str,
        target: tuple[Path, str, str],
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> bool:
        token.raise_if_cancelled()
        result = self.runner.run(
            (*target, "shell", "pm", "path", package_name),
            log=log,
            check=False,
        )
        return result.returncode == 0 and any(
            line.strip().startswith("package:") for line in result.output
        )

    @staticmethod
    def _confirmed_success(output: tuple[str, ...]) -> bool:
        return any(line.strip().lower() == "success" for line in output)

    def _remote_file_size(
        self,
        target: tuple[Path, str, str],
        remote_path: str,
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> int | None:
        for command in (
            (*target, "shell", "stat", "-c", "%s", remote_path),
            (*target, "shell", "toybox", "stat", "-c", "%s", remote_path),
        ):
            token.raise_if_cancelled()
            result = self.runner.run(
                command,
                log=log,
                check=False,
            )
            for line in reversed(result.output):
                if line.strip().isdigit():
                    return int(line.strip())
        return None
