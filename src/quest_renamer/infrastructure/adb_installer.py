"""Cancellable, verified installation on one authorized Quest."""

from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
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

_OBB_NAME = re.compile(r"[A-Za-z0-9._-]+\.obb", re.IGNORECASE)
_STAGING_NAME = re.compile(r"\.qar-new-[0-9a-f]{12}-\d+-[A-Za-z0-9._-]+\.obb", re.IGNORECASE)
_INSTALL_FAILURE = re.compile(r"Failure\s*\[(INSTALL_[A-Z_]+)(?::\s*(.*?))?\]", re.IGNORECASE)
_INSTALL_FAILURE_TEXT = {
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE": (
        "The app on the Quest was signed with a different key. Uninstall it first, "
        "or build this copy with the saved signing identity for that app."
    ),
    "INSTALL_FAILED_VERSION_DOWNGRADE": (
        "The Quest already has a newer version of this app. Uninstall it first to "
        "install an older build."
    ),
    "INSTALL_FAILED_INSUFFICIENT_STORAGE": (
        "The Quest does not have enough free storage for this APK."
    ),
    "INSTALL_FAILED_OLDER_SDK": (
        "This APK requires a newer Android version than the Quest firmware provides."
    ),
    "INSTALL_FAILED_NO_MATCHING_ABIS": (
        "This APK does not contain native code for the Quest's processor."
    ),
    "INSTALL_PARSE_FAILED_NO_CERTIFICATES": (
        "The APK is not signed. Enable APK signing and rebuild it."
    ),
    "INSTALL_FAILED_USER_RESTRICTED": (
        "Installing apps over USB is blocked on the Quest. Check Developer settings."
    ),
    "INSTALL_FAILED_VERIFICATION_FAILURE": (
        "The Quest rejected the APK signature during verification."
    ),
    "INSTALL_FAILED_INVALID_APK": "The Quest reported that the APK file is invalid.",
}

# Seconds between remote size probes while a large OBB is being pushed.
_PUSH_PROGRESS_INTERVAL = 1.5


@dataclass(frozen=True, slots=True)
class _RemoteObb:
    name: str
    path: str
    size: int


@dataclass(frozen=True, slots=True)
class _PreparedObb:
    source: Path
    remote_path: str
    size: int
    action: str
    staged_path: str = ""
    reused_path: str = ""
    backup_path: str = ""
    # Whether a file already occupied remote_path before activation and was moved aside.
    remote_existed: bool = False


def classify_install_failure(output: Iterable[str]) -> str:
    """Return a readable explanation for an ``adb install`` failure, or ``""``."""
    for line in output:
        match = _INSTALL_FAILURE.search(line)
        if match is None:
            continue
        code = match.group(1).upper()
        detail = (match.group(2) or "").strip()
        friendly = _INSTALL_FAILURE_TEXT.get(code)
        if friendly:
            return f"{friendly} ({code})"
        return f"The Quest rejected the APK: {code}" + (f" — {detail}" if detail else "")
    return ""


def format_transfer_rate(bytes_per_second: float) -> str:
    if bytes_per_second >= 1024**2:
        return f"{bytes_per_second / 1024**2:.0f} MB/s"
    return f"{bytes_per_second / 1024:.0f} KB/s"


def format_eta(seconds: float) -> str:
    if seconds < 1:
        return "almost done"
    if seconds < 60:
        return f"~{int(seconds)} s left"
    minutes, rest = divmod(int(seconds), 60)
    return f"~{minutes} min {rest:02d} s left"


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
        apk_installed = False
        try:
            self._activate_prepared_obbs(prepared, target, token, log)
            activated = True
            token.raise_if_cancelled()
            progress(0.68, "Installing APK")
            self._install_apk(bundle, target, token, progress, log)
            apk_installed = True
            progress(0.86, "APK installed • verifying package and OBB files")
            self._verify_prepared_obbs(prepared, target, token, log)
            self._verify_package(bundle.package_name, target, token, progress, log)
            # Only a bundle that supplies the complete OBB set may prune others.
            expected = {obb.name for obb in bundle.obbs} if bundle.obbs else None
            self._finish_obb_sync(bundle, prepared, target, token, log, expected=expected)
            progress(1.0, "Install verified")
        except BundleInstallError as exc:
            exc.apk_installed = apk_installed
            self._undo_after_failure(prepared, activated, target, log)
            raise
        except Exception:
            self._undo_after_failure(prepared, activated, target, log)
            raise
        return BundleInstallResult(
            bundle.package_name,
            bundle.apk,
            self._installed_obbs(prepared),
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
        keep_obb_names: tuple[str, ...] = (),
    ) -> BundleInstallResult:
        """Re-synchronize only ``bundle.obbs`` without touching the installed APK.

        ``keep_obb_names`` lists the complete OBB set of the installed game. When it is
        provided, obsolete package-owned files outside that set are pruned after
        verification; otherwise nothing else in the package folder is removed.
        """
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
        except BundleInstallError as exc:
            exc.apk_installed = True
            self._rollback_prepared_obbs(prepared, target, log)
            raise
        except Exception:
            self._rollback_prepared_obbs(prepared, target, log)
            raise
        expected = (
            set(keep_obb_names) | {obb.name for obb in bundle.obbs} if keep_obb_names else None
        )
        self._finish_obb_sync(bundle, prepared, target, token, log, expected=expected)
        progress(1.0, "OBB retry verified")
        return BundleInstallResult(
            bundle.package_name,
            bundle.apk,
            self._installed_obbs(prepared),
            True,
        )

    def uninstall_package(
        self,
        package_name: str,
        serial: str,
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        """Remove an installed package so a differently signed copy can be installed."""
        log = log or (lambda _message: None)
        if not is_valid_package_id(package_name):
            raise BundleInstallError("The package ID to uninstall is not valid.")
        adb = find_adb(resource_root=self.resource_root, executable=self.executable)
        if adb is None:
            raise BundleInstallError("ADB is not available.")
        if not serial:
            raise BundleInstallError("No authorized Quest is selected.")
        result = self.runner.run(
            (adb, "-s", serial, "uninstall", package_name), log=log, check=False
        )
        if not self._confirmed_success(result.output):
            detail = next((line for line in reversed(result.output) if line.strip()), "")
            raise BundleInstallError(
                f"The Quest did not confirm that {package_name} was uninstalled."
                + (f" ({detail})" if detail else "")
            )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _installed_obbs(prepared: tuple[_PreparedObb, ...]) -> tuple[InstalledObb, ...]:
        return tuple(
            InstalledObb(item.source, item.remote_path, item.size, item.action)
            for item in prepared
        )

    def _undo_after_failure(
        self,
        prepared: tuple[_PreparedObb, ...],
        activated: bool,
        target: tuple[Path, str, str],
        log: Callable[[str], None],
    ) -> None:
        if activated:
            log("Install verification failed; restoring the previous OBB set.")
            self._rollback_prepared_obbs(prepared, target, log)
        else:
            self._remove_staged_obbs(prepared, target, log)

    def _install_apk(
        self,
        bundle: BundleDraft,
        target: tuple[Path, str, str],
        token: CancellationToken,
        progress: Callable[[float, str], None],
        log: Callable[[str], None],
    ) -> None:
        started = time.monotonic()
        stop = threading.Event()

        def heartbeat() -> None:
            # adb prints nothing while streaming a large APK; keep the label alive.
            while not stop.wait(2.0):
                elapsed = int(time.monotonic() - started)
                progress(0.68 + min(0.16, elapsed / 600), f"Installing APK • {elapsed} s")

        ticker = threading.Thread(target=heartbeat, daemon=True)
        ticker.start()
        try:
            apk_result = self.runner.run(
                (*target, "install", "-r", "-g", bundle.apk),
                token=token,
                log=log,
                check=False,
            )
        finally:
            stop.set()
        if apk_result.returncode == 0 and self._confirmed_success(apk_result.output):
            return
        reason = classify_install_failure(apk_result.output)
        if reason:
            raise BundleInstallError(reason)
        detail = next(
            (line.strip() for line in reversed(apk_result.output) if line.strip()),
            "",
        )
        if apk_result.returncode != 0:
            raise BundleInstallError(
                "ADB could not install the APK"
                + (f": {detail}" if detail else f" (exit code {apk_result.returncode}).")
            )
        raise BundleInstallError("ADB finished without confirming a successful APK install.")

    def _validated_target(self, bundle: BundleDraft, serial: str) -> tuple[Path, str, str]:
        if not bundle.apk.is_file() or bundle.apk.suffix.lower() != ".apk":
            raise BundleInstallError("The finished folder does not contain a readable APK.")
        if not is_valid_package_id(bundle.package_name):
            raise BundleInstallError("The finished folder does not contain a valid package ID.")
        for obb in bundle.obbs:
            if not obb.is_file():
                raise BundleInstallError(f"The OBB file is missing: {obb.name}")
            if not _OBB_NAME.fullmatch(obb.name):
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
        remote_digests: dict[str, str] = {}
        used_remote: set[str] = set()
        prepared: list[_PreparedObb] = []
        total = len(bundle.obbs)
        for index, obb in enumerate(bundle.obbs, start=1):
            token.raise_if_cancelled()
            remote_path = f"{remote_root}/{obb.name}"
            size = obb.stat().st_size
            remote_existed = obb.name in remote
            progress(
                0.06 + ((index - 1) / total) * 0.05,
                f"Comparing OBB {index} of {total} • {obb.name}",
            )
            same_name = remote.get(obb.name)
            local_hash = ""
            if same_name is not None and same_name.size == size:
                local_hash = self._local_sha256(obb, token)
                remote_hash = self._remote_sha256(
                    target, same_name.path, token, log, cache=remote_digests
                )
                if remote_hash and remote_hash == local_hash:
                    log(f"OBB already matches on Quest; skipping transfer: {obb.name}")
                    prepared.append(
                        _PreparedObb(obb, remote_path, size, "unchanged", remote_existed=True)
                    )
                    used_remote.add(same_name.name)
                    continue

            reusable: _RemoteObb | None = None
            for candidate in remote.values():
                if (
                    candidate.name in used_remote
                    or candidate.name == obb.name
                    or candidate.size != size
                ):
                    continue
                if not local_hash:
                    local_hash = self._local_sha256(obb, token)
                candidate_hash = self._remote_sha256(
                    target, candidate.path, token, log, cache=remote_digests
                )
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
                        remote_existed=remote_existed,
                    )
                )
                continue

            staged = f"{remote_root}/.qar-new-{transaction_id}-{index}-{obb.name}"
            base_progress = 0.12 + ((index - 1) / total) * 0.46
            span = 0.46 / total
            progress(base_progress, self._copy_label(index, total, obb.name, size))
            def report_push(
                fraction: float,
                detail: str,
                *,
                base: float = base_progress,
                span: float = span,
                index: int = index,
                name: str = obb.name,
                size: int = size,
            ) -> None:
                progress(
                    base + span * fraction,
                    self._copy_label(index, total, name, size, detail),
                )

            try:
                self._push_with_progress(target, obb, staged, size, token, log, report_push)
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
                self._remove_remote(target, staged, log)
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
                    remote_existed=remote_existed,
                )
            )
        progress(0.62, "OBB set prepared safely")
        return tuple(prepared)

    def _push_with_progress(
        self,
        target: tuple[Path, str, str],
        source: Path,
        staged: str,
        size: int,
        token: CancellationToken,
        log: Callable[[str], None],
        report: Callable[[float, str], None],
    ) -> None:
        """Run ``adb push`` while a helper thread samples the staged size for progress."""
        stop = threading.Event()

        def quiet(_message: str) -> None:
            """Size probes run every second or two; keep them out of the activity log."""

        def sample() -> None:
            started = time.monotonic()
            last_bytes = 0
            last_time = started
            # Wait before the first probe so short pushes never spawn extra commands.
            while not stop.wait(_PUSH_PROGRESS_INTERVAL):
                try:
                    current = self._remote_file_size(target, staged, CancellationToken(), quiet)
                except Exception:
                    continue
                if current is None or size <= 0:
                    continue
                now = time.monotonic()
                rate = (current - last_bytes) / max(0.001, now - last_time)
                last_bytes, last_time = current, now
                fraction = min(1.0, current / size)
                detail = f"{current / 1024**2:.0f} MB of {size / 1024**2:.0f} MB"
                if rate > 0:
                    remaining = (size - current) / rate
                    detail += f" • {format_transfer_rate(rate)} • {format_eta(remaining)}"
                report(fraction, detail)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        try:
            self.runner.run((*target, "push", source, staged), token=token, log=log)
        finally:
            stop.set()
            sampler.join(timeout=0.5)

    def _remove_transaction_staging(
        self,
        bundle: BundleDraft,
        target: tuple[Path, str, str],
        log: Callable[[str], None],
    ) -> None:
        remote_root = f"/sdcard/Android/obb/{bundle.package_name}"
        # "-a" is required: staged files are dotfiles, which ls hides by default.
        result = self.runner.run(
            (*target, "shell", "ls", "-1a", remote_root),
            log=log,
            check=False,
        )
        stale = [
            f"{remote_root}/{name}"
            for raw in result.output
            if (name := raw.strip()).startswith(".qar-new-") and _STAGING_NAME.fullmatch(name)
        ]
        if stale:
            self._remove_remote_many(target, stale, log)

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
                if item.remote_existed:
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
        if not prepared:
            return
        token.raise_if_cancelled()
        # Every prepared file lives in the same package folder; size them in one call.
        remote_root = prepared[0].remote_path.rsplit("/", 1)[0]
        remote = self._remote_obbs(target, remote_root, token, log)
        for item in prepared:
            token.raise_if_cancelled()
            current = remote.get(item.source.name)
            size = (
                current.size
                if current is not None
                else self._remote_file_size(target, item.remote_path, token, log)
            )
            if size != item.size:
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
        *,
        expected: set[str] | None,
    ) -> None:
        token.raise_if_cancelled()
        backups = [
            item.backup_path for item in prepared if item.backup_path and item.remote_existed
        ]
        if backups:
            self._remove_remote_many(target, backups, log)
        if expected is None:
            if prepared:
                log("Existing OBB files outside this transfer were left untouched.")
            return
        remote_root = f"/sdcard/Android/obb/{bundle.package_name}"
        remote = self._remote_obbs(target, remote_root, token, log)
        previously_managed = set(bundle.managed_obb_names)
        obsolete: list[str] = []
        for remote_item in remote.values():
            if remote_item.name in expected:
                continue
            parsed = parse_obb_filename(remote_item.name)
            belongs_to_package = bool(
                parsed is not None
                and parsed.package_name.casefold() == bundle.package_name.casefold()
            )
            if belongs_to_package or remote_item.name in previously_managed:
                log(
                    f"Removing obsolete versioned OBB after verified update: {remote_item.name}"
                )
                obsolete.append(remote_item.path)
        if obsolete:
            self._remove_remote_many(target, obsolete, log)

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
            if item.remote_existed and item.backup_path:
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
        staged = [item.staged_path for item in prepared if item.staged_path]
        if staged:
            self._remove_remote_many(target, staged, log)

    def _remote_obbs(
        self,
        target: tuple[Path, str, str],
        remote_root: str,
        token: CancellationToken,
        log: Callable[[str], None],
    ) -> dict[str, _RemoteObb]:
        """List visible OBB files with their sizes using one remote command.

        ``stat`` formats carry no spaces so adb's unquoted argument forwarding cannot
        split them; the remote shell expands the glob itself.
        """
        token.raise_if_cancelled()
        remote: dict[str, _RemoteObb] = {}
        for prefix in (("stat",), ("toybox", "stat")):
            result = self.runner.run(
                (*target, "shell", *prefix, "-c", "%s:%n", f"{remote_root}/*"),
                token=token,
                log=log,
                check=False,
            )
            found_any = False
            for raw in result.output:
                size_text, separator, path = raw.strip().partition(":")
                if not separator or not size_text.isdigit():
                    continue
                found_any = True
                name = path.rsplit("/", 1)[-1]
                if name.startswith(".qar-") or not _OBB_NAME.fullmatch(name):
                    continue
                remote[name] = _RemoteObb(name, f"{remote_root}/{name}", int(size_text))
            if found_any or result.returncode == 0:
                break
        if remote or found_any:
            return remote
        # Fallback for shells without stat: list names, then size each one.
        listing = self.runner.run(
            (*target, "shell", "ls", "-1", remote_root),
            token=token,
            log=log,
            check=False,
        )
        for raw in listing.output:
            name = raw.strip()
            if name.startswith(".qar-") or not _OBB_NAME.fullmatch(name):
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
        *,
        cache: dict[str, str] | None = None,
    ) -> str:
        if cache is not None and path in cache:
            return cache[path]
        digest_value = ""
        for command in (
            (*target, "shell", "sha256sum", path),
            (*target, "shell", "toybox", "sha256sum", path),
        ):
            token.raise_if_cancelled()
            result = self.runner.run(command, log=log, check=False)
            for line in result.output:
                digest = line.strip().split(maxsplit=1)[0].lower()
                if re.fullmatch(r"[0-9a-f]{64}", digest):
                    digest_value = digest
                    break
            if digest_value:
                break
        if cache is not None:
            cache[path] = digest_value
        return digest_value

    @staticmethod
    def _copy_label(index: int, count: int, name: str, size: int, detail: str = "") -> str:
        if size >= 1024**3:
            formatted = f"{size / (1024**3):.2f} GB"
        else:
            formatted = f"{size / (1024**2):.1f} MB"
        label = f"Uploading changed OBB {index} of {count} • {name} • {formatted}"
        return f"{label} • {detail}" if detail else label

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

    def _remove_remote_many(
        self,
        target: tuple[Path, str, str],
        paths: list[str],
        log: Callable[[str], None],
    ) -> None:
        # Names are regex-validated, so they can be passed unquoted in one command.
        for start in range(0, len(paths), 32):
            self.runner.run(
                (*target, "shell", "rm", "-f", *paths[start : start + 32]),
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
        if not self._package_is_installed(package_name, target, token, log):
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
