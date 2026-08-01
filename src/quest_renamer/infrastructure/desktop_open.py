"""Open local files and folders without depending on one Qt desktop backend."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

Launcher = Callable[[Sequence[str]], object]


def external_process_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Restore host library paths before starting desktop applications.

    PyInstaller adjusts library and Qt lookup variables for its child process.
    Passing those values to KDE/GNOME helpers can make a host file manager load
    the app's bundled libraries instead of the distro's matching versions.
    """
    source = os.environ if environment is None else environment
    result = dict(source)
    original_ld_path = result.pop("LD_LIBRARY_PATH_ORIG", None)
    if original_ld_path:
        result["LD_LIBRARY_PATH"] = original_ld_path
    elif "_MEIPASS2" in result or "APPIMAGE" in result:
        result.pop("LD_LIBRARY_PATH", None)
    for name in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        result.pop(name, None)
    return result


def desktop_open_commands(
    path: Path,
    *,
    platform_name: str = sys.platform,
    environment: Mapping[str, str] | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Return native launcher commands in desktop-appropriate fallback order."""
    value = str(path)
    if platform_name == "darwin":
        return (("open", value),)
    if platform_name.startswith("win"):
        return (("explorer.exe", value),)
    if not platform_name.startswith("linux"):
        return ()

    values = os.environ if environment is None else environment
    desktop = " ".join(
        str(values.get(name, ""))
        for name in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION")
    ).lower()
    if any(name in desktop for name in ("kde", "plasma", "lxqt")):
        return (
            ("kioclient6", "exec", value),
            ("kioclient5", "exec", value),
            ("kde-open5", value),
            ("xdg-open", value),
            ("gio", "open", value),
        )
    return (("gio", "open", value), ("xdg-open", value))


def open_local_path(
    path: Path,
    *,
    platform_name: str = sys.platform,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    launcher: Launcher | None = None,
) -> bool:
    """Start a host file manager or associated app without invoking a shell."""
    target = path.expanduser().resolve(strict=False)
    if not target.exists():
        return False

    if platform_name.startswith("win"):
        startfile = getattr(os, "startfile", None)
        if callable(startfile):
            try:
                startfile(str(target))
            except OSError:
                pass
            else:
                return True

    def default_launcher(command: Sequence[str]) -> object:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=not platform_name.startswith("win"),
            env=external_process_environment(environment),
        )

    start = launcher or default_launcher
    for command in desktop_open_commands(
        target,
        platform_name=platform_name,
        environment=environment,
    ):
        executable = which(command[0])
        if executable is None:
            continue
        try:
            start((executable, *command[1:]))
        except OSError:
            continue
        return True
    return False
