"""Portable output copying and metadata generation."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from quest_renamer import __version__
from quest_renamer.domain.build import PackageRewriteReport
from quest_renamer.domain.models import BuildRequest
from quest_renamer.domain.operations import CancellationToken

OBB_NAME = re.compile(r"^(main|patch)\.(\d+)\.(.+)\.obb$", re.IGNORECASE)


def copy_file(
    source: Path,
    destination: Path,
    *,
    token: CancellationToken,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = source.stat().st_size
    copied = 0
    with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
        while chunk := source_handle.read(8 * 1024 * 1024):
            token.raise_if_cancelled()
            destination_handle.write(chunk)
            copied += len(chunk)
            if progress:
                progress(copied, total)
    shutil.copystat(source, destination)


def obb_destination(source: Path, request: BuildRequest, output_root: Path) -> Path:
    match = OBB_NAME.match(source.name)
    kind = match.group(1).lower() if match else "main"
    version = request.source.version_code or (match.group(2) if match else "1")
    return output_root / request.package_name / f"{kind}.{version}.{request.package_name}.obb"


def write_release_manifest(
    request: BuildRequest,
    output_root: Path,
    apk: Path,
    obbs: tuple[Path, ...],
) -> Path:
    total_size = apk.stat().st_size + sum(path.stat().st_size for path in obbs)
    updated = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows = [
        ["#VRPRELEASEMANIFEST 1.0"],
        [
            "Game Name",
            "Release Name",
            "Package Name",
            "Version Code",
            "Last Updated",
            "Size (MB)",
            "Downloads",
            "Rating",
            "Rating Count",
        ],
        [
            request.source.game_name or request.package_name,
            output_root.name,
            request.package_name,
            request.source.version_code or "1",
            updated,
            str(round(total_size / 1_000_000)),
            "0",
            "0",
            "0",
        ],
        [],
        ["#filelist"],
        ["type", "name", "size"],
        ["f", f"./{apk.name}", str(apk.stat().st_size)],
    ]
    if obbs:
        rows.append(["d", f"./{request.package_name}", "0"])
        rows.extend(
            ["f", f"./{obb.relative_to(output_root).as_posix()}", str(obb.stat().st_size)]
            for obb in obbs
        )
    path = output_root / "release.manifest"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerows(rows)
    return path


def sha256_file(path: Path, token: CancellationToken) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            token.raise_if_cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def write_build_report(
    request: BuildRequest,
    output_root: Path,
    apk: Path,
    obbs: tuple[Path, ...],
    rewrite: PackageRewriteReport,
    *,
    token: CancellationToken,
) -> Path:
    created = dt.datetime.now(dt.UTC)
    source_signer = (
        request.source.signer_identity.full_name
        if request.source.signer_identity is not None
        else "Unrecognized or unavailable"
    )
    apk_hash = sha256_file(apk, token)
    obb_rows = [
        {
            "source": request.source.obbs[index].name
            if index < len(request.source.obbs)
            else "",
            "output": path.relative_to(output_root).as_posix(),
            "size": path.stat().st_size,
        }
        for index, path in enumerate(obbs)
    ]
    report = {
        "report_version": 2,
        "created_utc": created.isoformat(),
        "application": {"name": "Quest APK Renamer", "version": __version__},
        "source": {
            "folder": str(request.source.root),
            "apk": request.source.apk.name,
            "apk_size": request.source.apk.stat().st_size,
            "game_name": request.source.game_name,
            "version_code": request.source.version_code,
            "signer": source_signer,
        },
        "output": {
            "folder": str(request.output_root),
            "mode": "replace_source" if request.replace_source else "separate_copy",
        },
        "packages": {
            "source": request.source.package_name,
            "output": request.package_name,
        },
        "patches": list(request.patches),
        "apk": {
            "name": apk.name,
            "size": apk.stat().st_size,
            "sha256": apk_hash,
            "signed": request.sign_apk,
            "signature_verified": request.sign_apk,
        },
        "obbs": obb_rows,
        "rewrite": {
            "changed_files": rewrite.changed_files,
            "changed_occurrences": rewrite.changed_occurrences,
            "preserved_files": list(rewrite.preserved_files),
        },
        "preserved_game_content": True,
        "notes": [
            "The Android package ID and matching expansion-file paths were changed.",
            "The game name, assets, and in-game text were not intentionally changed.",
            "See preserved_files before debugging hard-coded or compiled package references.",
        ],
    }
    report_json = json.dumps(report, indent=2) + "\n"
    path = output_root / "RENAME-REPORT.json"
    path.write_text(report_json, encoding="utf-8")
    # This parseable copy is the private safety marker used before cleanup. Keep it
    # separate from the original app's public report filename so older previews
    # and interrupted migrations remain recognizable.
    (output_root / "quest-renamer-report.json").write_text(
        report_json,
        encoding="utf-8",
    )

    def size(value: int) -> str:
        amount = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if amount < 1000 or unit == "TB":
                return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
            amount /= 1000
        return f"{value} B"

    patches = ", ".join(request.patches) or "None"
    preserved = (
        "\n".join(f"  - {name}" for name in rewrite.preserved_files)
        if rewrite.preserved_files
        else "  None reported"
    )
    obb_text = (
        "\n".join(
            f"  - {row['source']}\n    → {row['output']} ({size(path.stat().st_size)})"
            for row, path in zip(obb_rows, obbs, strict=True)
        )
        if obb_rows
        else "  None"
    )
    text_report = (
        "\n".join(
            [
                "QUEST APK RENAMER — BUILD AND CHANGE REPORT",
                "=" * 52,
                f"Created: {created.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                f"App version: {__version__}",
                "",
                "SUMMARY",
                "-------",
                f"Source package: {request.source.package_name}",
                f"New package:    {request.package_name}",
                "Output mode:    "
                + ("Replace source safely" if request.replace_source else "Separate copy"),
                f"Source folder:  {request.source.root}",
                f"Output folder:  {request.output_root}",
                "",
                "APK",
                "---",
                f"Source file:     {request.source.apk.name} "
                f"({size(request.source.apk.stat().st_size)})",
                f"Finished file:   {apk.name} ({size(apk.stat().st_size)})",
                f"Version code:    {request.source.version_code or 'Not reported'}",
                f"Source signer:   {source_signer}",
                f"Signing:         {'Signed and verified' if request.sign_apk else 'Disabled'}",
                f"Finished SHA-256: {apk_hash}",
                "",
                "CHANGES",
                "-------",
                f"Technical references changed: {rewrite.changed_occurrences}",
                f"Decoded files changed:         {rewrite.changed_files}",
                f"Compatibility patches:         {patches}",
                f"OBB files renamed:              {len(obbs)}",
                "Game name and in-game text:     Left unchanged",
                "",
                "OBB FILES",
                "---------",
                obb_text,
                "",
                "PRESERVED REFERENCES",
                "--------------------",
                "These files contained references that were deliberately preserved because",
                "rewriting unknown, binary, or compiled content could damage the game:",
                preserved,
                "",
                "WHAT TO KEEP",
                "------------",
                "Keep your Quest APK Renamer signing-key backup. Android requires the same",
                "private key when installing future updates over this renamed package.",
                "",
                "The JSON report beside this file contains the same data in "
                "machine-readable form.",
            ]
        )
        + "\n"
    )
    text_path = output_root / "RENAME-REPORT.txt"
    text_path.write_text(text_report, encoding="utf-8")
    (output_root / "quest-renamer-report.txt").write_text(text_report, encoding="utf-8")

    summary_path = output_root / "RENAMED-BUNDLE.txt"
    summary_path.write_text(
        "\n".join(
            [
                f"Quest APK Renamer {__version__}",
                f"Source package: {request.source.package_name}",
                f"New package: {request.package_name}",
                f"Version code: {request.source.version_code or 'Not reported'}",
                f"APK: {apk.name}",
                f"OBB files: {len(obbs)}",
                f"Source signer: {source_signer}",
                "Change report: RENAME-REPORT.txt / RENAME-REPORT.json",
                "Older firmware compatibility: "
                + (
                    "applied"
                    if "older-firmware-compatibility" in request.patches
                    else "not applied"
                ),
                "Game name and in-game text: unchanged",
                "Signing: persistent local key" if request.sign_apk else "Signing: disabled",
                "",
                "Keep the signing-key backup. Future APK updates for this renamed",
                "package must use the same private key.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path
