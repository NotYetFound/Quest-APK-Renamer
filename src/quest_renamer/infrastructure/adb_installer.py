"""Cancellable, verified installation on one authorized Quest."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.installation import (
    BundleInstallError,
    BundleInstallResult,
    InstalledObb,
    InstalledPackageConflict,
)
from quest_renamer.domain.models import BundleDraft
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.domain.package_ids import is_valid_package_id
from quest_renamer.infrastructure.adb_device import find_adb
from quest_renamer.infrastructure.process_runner import ProcessRunner


class AdbApkInstaller:
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
        progress(0.04, "Installing APK")
        apk_result = self.runner.run(
            (*target, "install", "-r", "-g", bundle.apk),
            log=log,
        )
        if not self._confirmed_success(apk_result.output):
            raise BundleInstallError(
                "ADB finished without confirming a successful APK install."
            )
        progress(0.34, "APK installed")
        installed_obbs = self._transfer_obbs(
            bundle,
            target,
            token,
            progress,
            log,
            progress_start=0.34,
            progress_span=0.5,
        )
        self._verify_package(bundle.package_name, target, token, progress, log)
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
        installed_obbs = self._transfer_obbs(
            bundle,
            target,
            token,
            progress,
            log,
            progress_start=0.08,
            progress_span=0.78,
        )
        self._verify_package(bundle.package_name, target, token, progress, log)
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

    def _transfer_obbs(
        self,
        bundle: BundleDraft,
        target: tuple[Path, str, str],
        token: CancellationToken,
        progress: Callable[[float, str], None],
        log: Callable[[str], None],
        *,
        progress_start: float,
        progress_span: float,
    ) -> tuple[InstalledObb, ...]:
        installed_obbs: list[InstalledObb] = []
        remote_root = f"/sdcard/Android/obb/{bundle.package_name}"
        if bundle.obbs:
            token.raise_if_cancelled()
            self.runner.run(
                (*target, "shell", "mkdir", "-p", remote_root),
                log=log,
            )
        for index, obb in enumerate(bundle.obbs, start=1):
            token.raise_if_cancelled()
            remote_path = f"{remote_root}/{obb.name}"
            start = progress_start + ((index - 1) / len(bundle.obbs)) * progress_span
            progress(start, f"Copying OBB {index} of {len(bundle.obbs)}")
            try:
                self.runner.run(
                    (*target, "push", obb, remote_path),
                    log=log,
                )
                token.raise_if_cancelled()
                remote_size = self._remote_file_size(target, remote_path, token, log)
            except OperationCancelled:
                raise
            except Exception as exc:
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
            installed_obbs.append(InstalledObb(obb, remote_path, local_size))
        return tuple(installed_obbs)

    def _verify_package(
        self,
        package_name: str,
        target: tuple[Path, str, str],
        token: CancellationToken,
        progress: Callable[[float, str], None],
        log: Callable[[str], None],
    ) -> None:
        token.raise_if_cancelled()
        progress(0.9, "Verifying installed package")
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
        progress(1.0, "Install verified")

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
