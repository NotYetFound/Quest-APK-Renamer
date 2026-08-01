"""ADB discovery and read-only Quest device inspection."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.models import DeviceSnapshot


@dataclass(frozen=True, slots=True)
class AdbRecord:
    serial: str
    state: str
    attributes: dict[str, str]
    raw: str


def parse_adb_devices(output: str) -> tuple[AdbRecord, ...]:
    records: list[AdbRecord] = []
    for line in output.replace("\r", "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("List of devices") or stripped.startswith("*"):
            continue
        fields = stripped.split()
        if len(fields) < 2:
            continue
        serial, state = fields[:2]
        attributes: dict[str, str] = {}
        for field in fields[2:]:
            if ":" in field:
                key, value = field.split(":", 1)
                attributes[key] = value.replace("_", " ")
        records.append(AdbRecord(serial, state, attributes, stripped))
    return tuple(records)


def parse_available_storage(output: str) -> int | None:
    for line in reversed(output.replace("\r", "").splitlines()):
        fields = line.split()
        percent_index = next(
            (index for index, value in enumerate(fields) if re.fullmatch(r"\d+%", value)),
            None,
        )
        if percent_index is None or percent_index < 2:
            continue
        available = fields[percent_index - 1]
        if available.isdigit():
            return int(available) * 1024
    return None


def _adb_candidates(
    *,
    resource_root: Path | None,
    executable: Path | None,
    environment: Mapping[str, str],
    home: Path,
    system: str,
) -> list[Path]:
    binary = "adb.exe" if system.startswith("win") else "adb"
    candidates: list[Path] = []
    override = environment.get("QAR_ADB")
    if override:
        candidates.append(Path(override).expanduser())
    if resource_root is not None:
        candidates.append(resource_root / "runtime" / "platform-tools" / binary)
    if executable is not None:
        candidates.append(executable.resolve().parent / "runtime" / "platform-tools" / binary)
    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if root := environment.get(variable):
            candidates.append(Path(root) / "platform-tools" / binary)

    if system.startswith("win"):
        local = Path(environment.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(environment.get("APPDATA", home / "AppData" / "Roaming"))
        candidates.extend(
            (
                local / "Android" / "Sdk" / "platform-tools" / binary,
                roaming / "SideQuest" / "platform-tools" / binary,
            )
        )
    elif system == "darwin":
        candidates.extend(
            (
                home / "Library" / "Android" / "sdk" / "platform-tools" / binary,
                Path(
                    "/Applications/SideQuest.app/Contents/Resources/app.asar.unpacked/build/platform-tools"
                )
                / binary,
            )
        )
    else:
        candidates.extend(
            (
                home / "Android" / "Sdk" / "platform-tools" / binary,
                Path("/opt/SideQuest/resources/app.asar.unpacked/build/platform-tools")
                / binary,
            )
        )
    return candidates


def find_adb(
    *,
    resource_root: Path | None = None,
    executable: Path | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    system: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    environment = environment if environment is not None else os.environ
    home = (home or Path.home()).expanduser()
    system = system or sys.platform
    binary = "adb.exe" if system.startswith("win") else "adb"

    seen: set[str] = set()
    for candidate in _adb_candidates(
        resource_root=resource_root,
        executable=executable,
        environment=environment,
        home=home,
        system=system,
    ):
        normalized = os.path.normcase(str(candidate.expanduser()))
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_file():
            return candidate.resolve()
    found = which(binary)
    return Path(found).resolve() if found else None


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class AdbDeviceService:
    def __init__(
        self,
        *,
        adb: Path | None = None,
        resource_root: Path | None = None,
        executable: Path | None = None,
        run: RunCommand = subprocess.run,
    ) -> None:
        self._configured_adb = adb
        self._resource_root = resource_root
        self._executable = executable
        self._run = run

    def _command(
        self, arguments: Sequence[str], timeout: int = 8
    ) -> subprocess.CompletedProcess[str]:
        creationflags = (
            int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if sys.platform.startswith("win")
            else 0
        )
        return self._run(
            list(arguments),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )

    def snapshot(self) -> DeviceSnapshot:
        adb = self._configured_adb or find_adb(
            resource_root=self._resource_root,
            executable=self._executable,
        )
        if adb is None:
            return DeviceSnapshot(
                False,
                status="tools_missing",
                detail="Android Platform Tools are not installed yet.",
            )
        try:
            result = self._command((str(adb), "devices", "-l"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DeviceSnapshot(False, status="error", detail=str(exc))
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "ADB returned an error."
            return DeviceSnapshot(False, status="error", detail=detail)

        records = parse_adb_devices(result.stdout)
        ready = [record for record in records if record.state == "device"]
        if len(ready) > 1:
            return DeviceSnapshot(
                False,
                status="multiple",
                detail="Disconnect other Android devices and leave one Quest connected.",
            )
        if not ready:
            if any(record.state == "unauthorized" for record in records):
                return DeviceSnapshot(
                    False,
                    status="unauthorized",
                    detail="Put on the headset and approve USB debugging.",
                )
            if any("no permissions" in record.raw.lower() for record in records):
                return DeviceSnapshot(
                    False,
                    status="permission",
                    detail="Install Android udev rules, then reconnect the headset.",
                )
            if records:
                return DeviceSnapshot(
                    False,
                    status="offline",
                    detail="Reconnect the headset and keep it awake.",
                )
            return DeviceSnapshot(
                False,
                status="disconnected",
                detail="Connect the headset by USB.",
            )

        record = ready[0]
        target = (str(adb), "-s", record.serial)
        model = record.attributes.get("model", "Quest")
        try:
            model_result = self._command((*target, "shell", "getprop", "ro.product.model"))
            if model_result.returncode == 0 and model_result.stdout.strip():
                model = model_result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass

        free_bytes = None
        try:
            storage_result = self._command((*target, "shell", "df", "-k", "/sdcard"))
            if storage_result.returncode == 0:
                free_bytes = parse_available_storage(storage_result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return DeviceSnapshot(
            True,
            status="connected",
            serial=record.serial,
            model=model,
            free_bytes=free_bytes,
            detail=f"Connected through {adb}",
        )
