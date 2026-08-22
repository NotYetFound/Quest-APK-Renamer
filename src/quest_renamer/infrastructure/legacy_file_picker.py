"""Last-resort desktop and Tk file pickers adapted from the released app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from quest_renamer.infrastructure.desktop_open import external_process_environment

PickerKind = Literal[
    "folder",
    "apk",
    "apks",
    "archive",
    "save_archive",
    "save_json",
    "save_log",
]
PickerRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class LegacyPickerResult:
    paths: tuple[Path, ...] = ()
    cancelled: bool = False
    errors: tuple[str, ...] = ()


def linux_dialog_order(environment: Mapping[str, str] | None = None) -> tuple[str, ...]:
    values = environment if environment is not None else os.environ
    desktop = next(
        (
            str(values.get(name, ""))
            for name in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION")
            if values.get(name)
        ),
        "",
    ).lower()
    if any(name in desktop for name in ("kde", "plasma", "lxqt")):
        return ("kdialog", "zenity", "yad")
    return ("zenity", "yad", "kdialog")


def linux_picker_command(
    helper: str,
    kind: PickerKind,
    title: str,
    start: PurePath,
    suggested_name: str = "",
) -> list[str]:
    if Path(helper).name == "kdialog":
        if kind == "folder":
            return [helper, "--title", title, "--getexistingdirectory", str(start)]
        if kind in {"save_archive", "save_json", "save_log"}:
            file_filter = (
                "*.qarlib|Quest APK Renamer Library (*.qarlib)"
                if kind == "save_archive"
                else "*.json|JSON report (*.json)"
                if kind == "save_json"
                else "*.log|Log files (*.log)"
            )
            return [
                helper,
                "--title",
                title,
                "--getsavefilename",
                str(start / suggested_name),
                file_filter,
            ]
        multiple = ["--multiple", "--separate-output"] if kind == "apks" else []
        return [
            helper,
            "--title",
            title,
            *multiple,
            "--getopenfilename",
            str(start),
            "*.qarlib|Quest APK Renamer Library (*.qarlib)"
            if kind == "archive"
            else "*.apk|Android packages (*.apk)",
        ]

    command = [helper, "--file-selection"]
    if kind == "folder":
        command.append("--directory")
    elif kind == "apks":
        command.extend(["--multiple", "--separator=\n"])
    elif kind in {"save_archive", "save_json", "save_log"}:
        command.extend(["--save", "--confirm-overwrite"])
    command.extend(
        [
            f"--title={title}",
            f"--filename={start / suggested_name}"
            if suggested_name
            else f"--filename={start}/",
        ]
    )
    if kind != "folder":
        label = (
            "Quest APK Renamer Library | *.qarlib"
            if kind in {"archive", "save_archive"}
            else "JSON report | *.json"
            if kind == "save_json"
            else "Log files | *.log"
            if kind == "save_log"
            else "Android packages | *.apk"
        )
        command.append(f"--file-filter={label}")
    return command


def _output_path(value: str) -> Path:
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme == "file":
        return Path(urllib.parse.unquote(parsed.path))
    return Path(value.strip())


def _command_failed(return_code: int, stderr: str) -> bool:
    if return_code == 0:
        return False
    detail = stderr.lower()
    markers = (
        "cannot open display",
        "could not connect to display",
        "failed to open display",
        "unable to init server",
        "no display",
        "qt.qpa",
        "platform plugin",
        "dbus",
        "not found",
        "traceback",
        "error:",
        "failed:",
    )
    return return_code not in {1, 5} or any(marker in detail for marker in markers)


def linux_desktop_pick(
    kind: PickerKind,
    title: str,
    start: Path,
    suggested_name: str,
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: PickerRunner = subprocess.run,
) -> LegacyPickerResult | None:
    """Use the current Linux desktop's own picker without a Qt/Tk fallback."""
    errors: list[str] = []
    for helper_name in linux_dialog_order(environment):
        helper = which(helper_name)
        if helper is None:
            continue
        try:
            completed = runner(
                linux_picker_command(helper, kind, title, start, suggested_name),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                env=external_process_environment(environment),
            )
        except OSError as exc:
            errors.append(f"{helper_name}: {exc}")
            continue
        if completed.returncode == 0:
            paths = tuple(
                _output_path(line) for line in completed.stdout.splitlines() if line.strip()
            )
            return LegacyPickerResult(paths=paths, cancelled=not paths, errors=tuple(errors))
        if not _command_failed(completed.returncode, completed.stderr):
            return LegacyPickerResult(cancelled=True, errors=tuple(errors))
        detail = completed.stderr.strip() or completed.stdout.strip()
        errors.append(f"{helper_name}: {detail or f'exited with {completed.returncode}'}")
    return LegacyPickerResult(errors=tuple(errors)) if errors else None


def legacy_fallback_pick(
    kind: PickerKind,
    title: str,
    start: Path,
    suggested_name: str = "",
) -> LegacyPickerResult:
    """Use the toolkit-independent final fallback after desktop and Qt pickers."""
    return _tk_pick(kind, title, start, suggested_name)


def _tk_pick(
    kind: PickerKind,
    title: str,
    start: Path,
    suggested_name: str,
) -> LegacyPickerResult:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except (ImportError, OSError) as exc:
        return LegacyPickerResult(errors=(f"Tk: {exc}",))
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            if kind == "folder":
                selected: object = filedialog.askdirectory(
                    title=title,
                    initialdir=str(start),
                    mustexist=True,
                )
            elif kind == "apks":
                selected = filedialog.askopenfilenames(
                    title=title,
                    initialdir=str(start),
                    filetypes=[("Android packages", "*.apk"), ("All files", "*")],
                )
            elif kind in {"save_archive", "save_json", "save_log"}:
                is_archive = kind == "save_archive"
                is_json = kind == "save_json"
                selected = filedialog.asksaveasfilename(
                    title=title,
                    initialdir=str(start),
                    initialfile=suggested_name,
                    defaultextension=(
                        ".qarlib" if is_archive else ".json" if is_json else ".log"
                    ),
                    filetypes=[
                        (
                            "Quest APK Renamer Library"
                            if is_archive
                            else "JSON report"
                            if is_json
                            else "Log files",
                            "*.qarlib"
                            if is_archive
                            else "*.json"
                            if is_json
                            else "*.log",
                        ),
                        ("All files", "*"),
                    ],
                )
            elif kind == "archive":
                selected = filedialog.askopenfilename(
                    title=title,
                    initialdir=str(start),
                    filetypes=[
                        ("Quest APK Renamer Library", "*.qarlib"),
                        ("All files", "*"),
                    ],
                )
            else:
                selected = filedialog.askopenfilename(
                    title=title,
                    initialdir=str(start),
                    filetypes=[("Android packages", "*.apk"), ("All files", "*")],
                )
        finally:
            root.destroy()
    except (OSError, RuntimeError, tk.TclError) as exc:
        return LegacyPickerResult(errors=(f"Tk: {exc}",))

    raw_paths = selected if isinstance(selected, (tuple, list)) else (selected,)
    paths = tuple(Path(str(value)) for value in raw_paths if str(value).strip())
    return LegacyPickerResult(paths=paths, cancelled=not paths)


def legacy_pick(
    kind: PickerKind,
    title: str,
    start: Path,
    suggested_name: str = "",
) -> LegacyPickerResult:
    helper_result: LegacyPickerResult | None = None
    if sys.platform.startswith("linux"):
        helper_result = linux_desktop_pick(kind, title, start, suggested_name)
        if helper_result is not None and (helper_result.paths or helper_result.cancelled):
            return helper_result
    tk_result = _tk_pick(kind, title, start, suggested_name)
    if helper_result is None:
        return tk_result
    return LegacyPickerResult(errors=helper_result.errors + tk_result.errors)
