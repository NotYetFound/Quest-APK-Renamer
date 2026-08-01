"""Safety checks for user-requested cleanup of old app-created output folders."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ManagedOutputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ManagedOutput:
    root: Path
    report: Path
    package_name: str
    apk_name: str
    total_size: int
    file_count: int


def inspect_managed_output(folder: Path) -> ManagedOutput:
    root = folder.expanduser().resolve()
    if not root.is_dir():
        raise ManagedOutputError("Choose an existing renamed output folder.")
    if root == Path.home().resolve() or root == Path(root.anchor):
        raise ManagedOutputError("That folder is too broad to clean safely.")
    report = root / "quest-renamer-report.json"
    if not report.is_file() or report.is_symlink():
        raise ManagedOutputError(
            "This is not a verified Quest APK Renamer output. "
            "The required build report is missing."
        )
    try:
        payload: Any = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagedOutputError("The build report is unreadable or damaged.") from exc
    if not isinstance(payload, dict):
        raise ManagedOutputError("The build report has an invalid format.")
    application = payload.get("application")
    packages = payload.get("packages")
    apk = payload.get("apk")
    if (
        not isinstance(application, dict)
        or application.get("name") != "Quest APK Renamer"
        or not isinstance(packages, dict)
        or not isinstance(apk, dict)
    ):
        raise ManagedOutputError("The folder was not created by this app.")
    package_name = str(packages.get("output") or "")
    apk_name = str(apk.get("name") or "")
    apk_path = root / apk_name
    if not package_name or not apk_name or apk_path.parent != root or not apk_path.is_file():
        raise ManagedOutputError("The finished APK named by the build report is missing.")
    total_size = 0
    file_count = 0
    try:
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                total_size += path.stat().st_size
                file_count += 1
    except OSError as exc:
        raise ManagedOutputError(f"The output size could not be checked: {exc}") from exc
    return ManagedOutput(root, report, package_name, apk_name, total_size, file_count)
