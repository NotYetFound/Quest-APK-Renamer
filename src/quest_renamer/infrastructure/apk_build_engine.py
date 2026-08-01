"""Transactional staged APK decode, rewrite, rebuild, sign, and output pipeline."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.build import BuildError, BuildResult
from quest_renamer.domain.models import BuildRequest
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.domain.signers import (
    build_lineage_dn,
    describe_previous_signer,
    rename_signature_text,
)
from quest_renamer.infrastructure.build_recovery import (
    clear_build_recovery,
    write_build_recovery,
)
from quest_renamer.infrastructure.bundle_output import (
    copy_file,
    obb_destination,
    write_build_report,
    write_release_manifest,
)
from quest_renamer.infrastructure.older_firmware_patch import (
    PATCH_ID,
    OlderFirmwarePatchError,
    apply_older_firmware_patch,
)
from quest_renamer.infrastructure.package_rewriter import replace_package_references
from quest_renamer.infrastructure.process_runner import CommandFailed, ProcessRunner
from quest_renamer.infrastructure.signing_identity import (
    SigningIdentityError,
    SigningIdentityStore,
)
from quest_renamer.infrastructure.toolchain import Toolchain

ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str], None]


def _unique_recovery_path(source: Path, label: str = "Original Backup") -> Path:
    base = source.parent / f"{source.name} — {label}"
    if not base.exists():
        return base
    number = 2
    while True:
        candidate = source.parent / f"{source.name} — {label} {number}"
        if not candidate.exists():
            return candidate
        number += 1


def activate_source_replacement(
    source: Path,
    staging: Path,
    move_to_trash: Callable[[Path], None] | None = None,
) -> Path | None:
    """Swap a verified sibling build into place and restore on activation failure."""
    source = source.resolve(strict=False)
    staging = staging.resolve(strict=False)
    if source == Path(source.anchor) or source == Path.home().resolve():
        raise BuildError("The selected source folder is too broad to replace safely.")
    if source.parent != staging.parent or ".staging-" not in staging.name:
        raise BuildError("The verified replacement is not a recognized sibling staging folder.")
    if not source.is_dir() or not staging.is_dir():
        raise BuildError("The source or verified replacement folder is no longer available.")

    recovery = _unique_recovery_path(source, "Source Backup")
    os.replace(source, recovery)
    try:
        os.replace(staging, source)
    except OSError as activation_error:
        try:
            if source.exists():
                raise OSError("the original source path was unexpectedly recreated")
            os.replace(recovery, source)
        except OSError as rollback_error:
            raise BuildError(
                "The replacement could not be activated or rolled back automatically. "
                f"The original folder is preserved at {recovery}. "
                f"Activation error: {activation_error}; rollback error: {rollback_error}",
                partial_output=staging,
            ) from activation_error
        raise BuildError(
            "The replacement could not be activated, so the original source folder was "
            "restored unchanged.",
            partial_output=staging,
        ) from activation_error
    if move_to_trash is not None:
        try:
            move_to_trash(recovery)
            return None
        except Exception:  # The platform adapter may wrap native errors differently.
            pass

    visible_recovery = _unique_recovery_path(source)
    try:
        os.replace(recovery, visible_recovery)
    except OSError:
        visible_recovery = recovery
    return visible_recovery


class StagedApkBuildEngine:
    def __init__(
        self,
        toolchain: Toolchain,
        *,
        signing_root: Path,
        cache_root: Path,
        runner: ProcessRunner | None = None,
        older_firmware_asset: Path | None = None,
        move_to_trash: Callable[[Path], None] | None = None,
        recovery_record: Path | None = None,
    ) -> None:
        self.toolchain = toolchain
        self.signing_root = signing_root
        self.cache_root = cache_root
        self.runner = runner or ProcessRunner()
        self.older_firmware_asset = older_firmware_asset
        self.move_to_trash = move_to_trash
        self.recovery_record = recovery_record

    def build(
        self,
        request: BuildRequest,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> BuildResult:
        token = token or CancellationToken()
        progress = progress or (lambda _value, _message: None)
        log = log or (lambda _message: None)
        if not self.toolchain.build_ready:
            raise BuildError(
                "; ".join(self.toolchain.problems) or "Build tools are unavailable."
            )
        assert self.toolchain.java is not None
        assert self.toolchain.keytool is not None
        assert self.toolchain.apktool is not None
        assert self.toolchain.signer is not None
        token.raise_if_cancelled()

        output = request.output_root.resolve(strict=False)
        source_root = request.source.root.resolve(strict=False)
        if request.replace_source:
            if output != source_root:
                raise BuildError("Source replacement must target the exact source folder.")
            if not source_root.is_dir() or request.source.apk.parent.resolve() != source_root:
                raise BuildError("The selected source is not a safe, direct game folder.")
            if request.source.obbs and not request.copy_obbs:
                raise BuildError(
                    "Source replacement requires OBB copying so the folder stays complete."
                )
        elif output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise BuildError("The output folder already exists and is not empty.")
        output.parent.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        framework = self.cache_root / "apktool-framework"
        framework.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
        ).resolve()
        if self.recovery_record is not None:
            write_build_recovery(
                self.recovery_record,
                staging=staging,
                source=source_root,
                output=output,
            )
        published = False
        log(f"Staging output beside its final destination: {staging.name}")

        try:
            progress(0.03, "Preparing isolated workspace")
            with tempfile.TemporaryDirectory(
                prefix="quest-renamer-build-", dir=self.cache_root
            ) as temporary:
                work = Path(temporary)
                decoded = work / "decoded"
                unsigned = work / f"{request.package_name}-unsigned.apk"
                signed = work / "signed"

                progress(0.06, "Decoding APK")
                self.runner.run(
                    (
                        self.toolchain.java,
                        "-jar",
                        self.toolchain.apktool,
                        "d",
                        "-f",
                        "-p",
                        framework,
                        request.source.apk,
                        "-o",
                        decoded,
                    ),
                    token=token,
                    log=log,
                )
                progress(0.30, "Updating app identity")
                rewrite = replace_package_references(
                    decoded,
                    request.source.package_name,
                    request.package_name,
                    token=token,
                    log=log,
                )
                if rewrite.changed_occurrences == 0:
                    raise BuildError(
                        "The original package ID was not found in the decoded Android files."
                    )
                if PATCH_ID in request.patches:
                    apply_older_firmware_patch(
                        decoded,
                        self.older_firmware_asset,
                        token=token,
                        log=log,
                    )

                progress(0.38, "Rebuilding APK")
                self.runner.run(
                    (
                        self.toolchain.java,
                        "-jar",
                        self.toolchain.apktool,
                        "b",
                        "-p",
                        framework,
                        decoded,
                        "-o",
                        unsigned,
                    ),
                    token=token,
                    log=log,
                )
                if not unsigned.is_file():
                    raise BuildError("Apktool completed but did not produce a rebuilt APK.")

                built_apk = unsigned
                if request.sign_apk:
                    progress(0.63, "Preparing signing identity")
                    previous_signer = describe_previous_signer(request.source.signer_identity)
                    signing_dname = None
                    if previous_signer:
                        signing_dname = build_lineage_dn(
                            signature_text=rename_signature_text(
                                request.source.package_name,
                                request.package_name,
                            ),
                            previous=previous_signer,
                        )
                        log(
                            "Embedding source signing lineage in the new certificate: "
                            f"previously signed by {previous_signer[0]} "
                            f"({previous_signer[1]})."
                        )
                    identity = SigningIdentityStore(
                        self.signing_root,
                        self.toolchain.keytool,
                        self.runner,
                    ).load_or_create(token=token, log=log, dname=signing_dname)
                    signed.mkdir()
                    progress(0.67, "Signing and aligning APK")
                    self.runner.run(
                        (
                            self.toolchain.java,
                            "-jar",
                            self.toolchain.signer,
                            "--apks",
                            unsigned,
                            "--out",
                            signed,
                            "--ks",
                            identity.keystore,
                            "--ksAlias",
                            identity.alias,
                            "--ksPass",
                            identity.password,
                            "--ksKeyPass",
                            identity.password,
                            "--allowResign",
                        ),
                        token=token,
                        log=log,
                        secret_values={identity.password},
                    )
                    candidates = sorted(signed.glob("*-aligned-signed.apk"))
                    if not candidates:
                        candidates = sorted(signed.glob("*.apk"))
                    if not candidates:
                        raise BuildError("The signer completed but did not produce an APK.")
                    built_apk = candidates[0]
                    progress(0.78, "Verifying APK signature")
                    self.runner.run(
                        (
                            self.toolchain.java,
                            "-jar",
                            self.toolchain.signer,
                            "--apks",
                            built_apk,
                            "--onlyVerify",
                        ),
                        token=token,
                        log=log,
                    )

                progress(0.83, "Saving APK")
                apk_output = staging / f"{request.package_name}.apk"
                copy_file(built_apk, apk_output, token=token)

                obb_outputs: list[Path] = []
                if request.copy_obbs and request.source.obbs:
                    total_bytes = sum(path.stat().st_size for path in request.source.obbs)
                    completed = 0
                    for index, source_obb in enumerate(request.source.obbs, start=1):
                        destination = obb_destination(source_obb, request, staging)
                        base = completed

                        def report_copy(
                            copied: int,
                            _total: int,
                            base_bytes: int = base,
                            item_index: int = index,
                        ) -> None:
                            fraction = (
                                (base_bytes + copied) / total_bytes if total_bytes else 1.0
                            )
                            progress(
                                0.85 + fraction * 0.10,
                                f"Copying OBB {item_index} of {len(request.source.obbs)}",
                            )

                        copy_file(
                            source_obb,
                            destination,
                            token=token,
                            progress=report_copy,
                        )
                        completed += source_obb.stat().st_size
                        obb_outputs.append(destination)

                progress(0.96, "Writing bundle metadata")
                manifest = write_release_manifest(
                    request, staging, apk_output, tuple(obb_outputs)
                )
                report = write_build_report(
                    request,
                    staging,
                    apk_output,
                    tuple(obb_outputs),
                    rewrite,
                    token=token,
                )
                token.raise_if_cancelled()

            recovery: Path | None = None
            if request.replace_source:
                progress(0.99, "Activating verified replacement")
                recovery = activate_source_replacement(
                    source_root,
                    staging,
                    self.move_to_trash,
                )
                if recovery is None:
                    log("Previous source moved to Trash after the verified swap.")
                else:
                    log(f"Trash was unavailable; previous source kept as: {recovery.name}")
            else:
                if output.exists():
                    output.rmdir()  # Preflight only permits an existing empty directory.
                os.replace(staging, output)
            published = True
            clear_build_recovery(self.recovery_record, staging)
            progress(1.0, "Build complete")
            final_apk = output / apk_output.relative_to(staging)
            final_obbs = tuple(output / path.relative_to(staging) for path in obb_outputs)
            return BuildResult(
                output,
                final_apk,
                final_obbs,
                output / manifest.relative_to(staging),
                output / report.relative_to(staging),
                rewrite,
                recovery,
                output / "RENAME-REPORT.txt",
            )
        except OperationCancelled:
            partial = staging if any(staging.iterdir()) else None
            if partial is None:
                shutil.rmtree(staging, ignore_errors=True)
                clear_build_recovery(self.recovery_record, staging)
            raise BuildError("Build cancelled safely.", partial_output=partial) from None
        except BuildError as exc:
            partial = staging if staging.exists() and any(staging.iterdir()) else None
            if partial is None:
                shutil.rmtree(staging, ignore_errors=True)
                clear_build_recovery(self.recovery_record, staging)
            raise BuildError(str(exc), partial_output=exc.partial_output or partial) from exc
        except (
            CommandFailed,
            OlderFirmwarePatchError,
            SigningIdentityError,
            OSError,
        ) as exc:
            partial = staging if staging.exists() and any(staging.iterdir()) else None
            if partial is None:
                shutil.rmtree(staging, ignore_errors=True)
                clear_build_recovery(self.recovery_record, staging)
            raise BuildError(str(exc), partial_output=partial) from exc
        except Exception:
            if not published and staging.exists() and not any(staging.iterdir()):
                shutil.rmtree(staging, ignore_errors=True)
                clear_build_recovery(self.recovery_record, staging)
            raise
