"""Fast automatic validation before expensive APK work begins."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from quest_renamer.domain.models import (
    BuildRequest,
    CheckState,
    DeviceSnapshot,
    ReadinessCheck,
)
from quest_renamer.domain.obb_names import ObbNameError, renamed_obb_filenames
from quest_renamer.domain.package_ids import package_id_error
from quest_renamer.domain.preflight import PreflightResult
from quest_renamer.infrastructure.older_firmware_patch import PATCH_ID

MIB = 1024 * 1024
GIB = 1024 * MIB


def default_output_folder(source: Path) -> Path:
    """Choose a visible sibling without nesting output inside the source."""
    return source.parent / f"{source.name} - Renamed"


def _same_or_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _host_space_requirement(apk_size: int, obb_size: int) -> int:
    # Apktool's decoded tree can be several times larger than the compressed APK.
    return max(768 * MIB, apk_size * 6 + obb_size + 256 * MIB)


def _quest_space_requirement(
    apk_size: int,
    obb_size: int,
    *,
    copy_obbs: bool,
) -> int:
    return int(apk_size * 1.25) + (obb_size if copy_obbs else 0) + 128 * MIB


def _existing_ancestor(path: Path) -> Path:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


class AutomaticPreflight:
    def __init__(
        self,
        *,
        tools_ready: bool,
        tool_problems: tuple[str, ...] = (),
        cache_root: Path | None = None,
    ) -> None:
        self.tools_ready = tools_ready
        self.tool_problems = tool_problems
        # Where apktool decodes and the signer writes; may be a different drive
        # from the output folder and must be checked separately.
        self.cache_root = cache_root

    def check(
        self,
        request: BuildRequest,
        *,
        device: DeviceSnapshot | None = None,
    ) -> PreflightResult:
        checks: list[ReadinessCheck] = []
        source = request.source
        apk_exists = source.apk.is_file()
        apk_size = 0
        if apk_exists:
            try:
                apk_size = source.apk.stat().st_size
            except OSError:
                apk_exists = False
        obb_size = 0
        obbs_exist = True
        for path in source.obbs:
            if not path.is_file():
                obbs_exist = False
                continue
            try:
                obb_size += path.stat().st_size
            except OSError:
                obbs_exist = False

        source_problem = ""
        if not apk_exists:
            source_problem = "The selected APK no longer exists."
        elif not os.access(source.apk, os.R_OK):
            source_problem = "The selected APK cannot be read."
        elif not obbs_exist:
            source_problem = "One or more selected OBB files no longer exist."
        elif source.obbs:
            try:
                renamed_obb_filenames(
                    source.obbs,
                    source_package=source.package_name,
                    target_package=request.package_name,
                )
            except ObbNameError as exc:
                source_problem = str(exc)
        checks.append(
            ReadinessCheck(
                "source",
                "Source files",
                CheckState.FAILED if source_problem else CheckState.PASSED,
                source_problem or "APK and expansion files are readable.",
            )
        )

        patch_only = (
            PATCH_ID in request.patches and request.package_name == source.package_name
        )
        identity_problem = package_id_error(
            request.package_name,
            source.package_name,
            allow_same=patch_only,
        )
        checks.append(
            ReadinessCheck(
                "identity",
                "New app ID",
                CheckState.FAILED if identity_problem else CheckState.PASSED,
                identity_problem
                or (
                    "The existing app ID will be kept for this patch-only build."
                    if patch_only
                    else "The new app ID is valid and separate."
                ),
            )
        )

        output_problem = ""
        output_detail = "A separate output folder is available."
        output = request.output_root.resolve(strict=False)
        source_root = source.root.resolve(strict=False)
        if request.replace_source:
            output_detail = (
                "The result will be verified before the source folder is swapped safely."
            )
            if output != source_root:
                output_problem = "Source replacement must use the exact source folder."
            elif (
                source_root == Path(source_root.anchor) or source_root == Path.home().resolve()
            ):
                output_problem = "This source folder is too broad to replace safely."
            elif not os.access(source_root.parent, os.W_OK):
                output_problem = "The source folder's parent cannot be written to."
            elif source.obbs and not request.copy_obbs:
                output_problem = (
                    "Source replacement requires OBB copying so the folder stays complete."
                )
        elif _same_or_inside(output, source_root):
            output_problem = "The output folder cannot be inside the source folder."
        elif _same_or_inside(source_root, output):
            output_problem = "The output folder cannot contain the source folder."
        elif output.exists() and (not output.is_dir() or any(output.iterdir())):
            output_problem = "The output folder already exists and is not empty."
        elif not os.access(_existing_ancestor(output.parent), os.W_OK):
            output_problem = "The save location cannot be written to."
        checks.append(
            ReadinessCheck(
                "output",
                "Output folder",
                CheckState.FAILED if output_problem else CheckState.PASSED,
                output_problem or output_detail,
            )
        )

        tools_detail = "; ".join(self.tool_problems)
        checks.append(
            ReadinessCheck(
                "tools",
                "Build tools",
                CheckState.PASSED if self.tools_ready else CheckState.FAILED,
                "Pinned build tools passed integrity checks."
                if self.tools_ready
                else tools_detail or "Required build tools are unavailable.",
            )
        )

        host_required = _host_space_requirement(apk_size, obb_size) if apk_exists else 0
        host_state = CheckState.PASSED
        host_detail = "There is enough working space on this computer."
        try:
            output_probe = _existing_ancestor(request.output_root.parent)
            # Decoded trees and the unsigned/signed APKs live in the cache; the final
            # APK and OBB copies land in the output. Check each drive for its share,
            # or the combined amount when both are on the same filesystem.
            cache_required = (apk_size * 6 + 256 * MIB) if apk_exists else 0
            output_required = (int(apk_size * 1.25) + obb_size) if apk_exists else 0
            cache_probe = (
                _existing_ancestor(self.cache_root) if self.cache_root is not None else None
            )
            same_drive = (
                cache_probe is None
                or os.stat(cache_probe).st_dev == os.stat(output_probe).st_dev
            )
            output_free = shutil.disk_usage(output_probe).free
            if same_drive:
                if output_free < host_required:
                    host_state = CheckState.FAILED
                    host_detail = (
                        "The output drive does not have enough free working space."
                    )
            else:
                assert cache_probe is not None
                cache_free = shutil.disk_usage(cache_probe).free
                if cache_free < max(512 * MIB, cache_required):
                    host_state = CheckState.FAILED
                    host_detail = (
                        "The app cache drive does not have enough free working space "
                        "for decoding and signing."
                    )
                elif output_free < output_required + 64 * MIB:
                    host_state = CheckState.FAILED
                    host_detail = "The output drive does not have enough free space."
        except OSError:
            host_state = CheckState.WARNING
            host_detail = "Free space on the output drive could not be checked."
        checks.append(ReadinessCheck("host_space", "Computer space", host_state, host_detail))

        quest_required = (
            _quest_space_requirement(
                apk_size,
                obb_size,
                copy_obbs=request.copy_obbs,
            )
            if apk_exists
            else 0
        )
        quest_state = CheckState.PASSED
        quest_detail = "The connected Quest has enough estimated free space."
        if device is None or not device.connected or device.free_bytes is None:
            quest_state = CheckState.WARNING
            quest_detail = "Quest capacity will be checked automatically before installation."
        elif device.free_bytes < quest_required:
            quest_state = CheckState.WARNING
            quest_detail = "The finished game may not fit on the connected Quest."
        checks.append(ReadinessCheck("quest_space", "Quest space", quest_state, quest_detail))

        return PreflightResult(tuple(checks), host_required, quest_required)
