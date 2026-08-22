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

from quest_renamer.domain.models import DeviceSnapshot, InstalledQuestApp


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


def parse_user_packages(output: str) -> tuple[str, ...]:
    """Parse `pm list packages` output without accepting shell noise as IDs."""
    return tuple(sorted(parse_user_package_versions(output), key=str.casefold))


def parse_user_package_versions(output: str) -> dict[str, str]:
    """Parse package IDs and optional `--show-versioncode` values in one pass."""
    packages: dict[str, str] = {}
    for line in output.replace("\r", "").splitlines():
        match = re.fullmatch(
            r"\s*package:([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)"
            r"(?:\s+versionCode:(\d+))?(?:\s+.*)?",
            line,
        )
        if match:
            packages[match.group(1)] = match.group(2) or ""
    return packages


def parse_package_versions(
    output: str,
    packages: set[str],
) -> dict[str, tuple[str, str]]:
    """Return version code/name pairs from one `dumpsys package packages` response."""
    versions: dict[str, tuple[str, str]] = {}
    current = ""
    version_code = ""
    version_name = ""

    def finish() -> None:
        if current in packages:
            versions[current] = (version_code, version_name)

    for raw in output.replace("\r", "").splitlines():
        match = re.match(r"\s*Package \[([^]]+)]", raw)
        if match:
            finish()
            candidate = match.group(1).strip()
            current = candidate if candidate in packages else ""
            version_code = ""
            version_name = ""
            continue
        if not current:
            continue
        stripped = raw.strip()
        if stripped.startswith("versionCode="):
            version_code = stripped.removeprefix("versionCode=").split()[0]
        elif stripped.startswith("versionName="):
            value = stripped.removeprefix("versionName=").strip()
            version_name = "" if value == "null" else value
    finish()
    return versions


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


_QUEST_PRODUCTS = frozenset(
    {
        # Meta/Oculus product code names reported by ``adb devices -l``.
        "monterey",  # Quest 1
        "hollywood",  # Quest 2
        "seacliff",  # Quest Pro
        "eureka",  # Quest 3
        "panther",  # Quest 3S
        "vr_monterey",
        "vr_hollywood",
    }
)


def _device_label(record: AdbRecord) -> str:
    model = record.attributes.get("model") or record.attributes.get("product") or ""
    return f"{model} ({record.serial})" if model else record.serial


def normalize_wireless_address(address: str) -> str:
    """Accept ``host``, ``host:port``, or ``adb connect host:port`` paste-ins."""
    value = address.strip()
    if value.lower().startswith("adb connect "):
        value = value[len("adb connect ") :].strip()
    if not value:
        raise OSError("Enter the headset's Wi-Fi address, for example 192.168.1.20:5555.")
    if ":" not in value:
        value = f"{value}:5555"
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise OSError("Use the form host:port, for example 192.168.1.20:5555.")
    return f"{host}:{port}"


def parse_wlan_address(output: str) -> str:
    match = re.search(r"inet\s+(\d{1,3}(?:\.\d{1,3}){3})/", output)
    return match.group(1) if match else ""


def parse_route_source(output: str) -> str:
    match = re.search(r"\bsrc\s+(\d{1,3}(?:\.\d{1,3}){3})", output)
    return match.group(1) if match else ""


def _looks_like_quest(record: AdbRecord) -> bool:
    values = " ".join(record.attributes.values()).casefold()
    return (
        "quest" in values
        or "oculus" in values
        or record.attributes.get("product", "").casefold() in _QUEST_PRODUCTS
    )


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
        self._resolved_adb: Path | None = None
        self._resource_root = resource_root
        self._executable = executable
        self._run = run
        self._models: dict[str, str] = {}
        self.preferred_serial = ""

    def set_preferred_serial(self, serial: str) -> None:
        self.preferred_serial = serial.strip()

    def _adb(self) -> Path | None:
        if self._configured_adb is not None:
            return self._configured_adb
        if self._resolved_adb is not None and self._resolved_adb.is_file():
            return self._resolved_adb
        self._resolved_adb = find_adb(
            resource_root=self._resource_root,
            executable=self._executable,
        )
        return self._resolved_adb

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
        adb = self._adb()
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
            # A phone or emulator next to the headset is common; prefer the one
            # device that identifies itself as a Quest, or the serial the user picked,
            # instead of refusing outright.
            preferred = [record for record in ready if record.serial == self.preferred_serial]
            quests = [record for record in ready if _looks_like_quest(record)]
            if preferred:
                ready = preferred
            elif len(quests) == 1:
                ready = quests
            else:
                return DeviceSnapshot(
                    False,
                    status="multiple",
                    detail="Several devices are attached. Choose the Quest to use.",
                    candidates=tuple(
                        (record.serial, _device_label(record)) for record in ready
                    ),
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
        model = self._models.get(record.serial, "")
        if not model:
            model = record.attributes.get("model", "Quest")
            try:
                model_result = self._command(
                    (*target, "shell", "getprop", "ro.product.model")
                )
                if model_result.returncode == 0 and model_result.stdout.strip():
                    model = model_result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
            if len(self._models) > 16:
                self._models.clear()
            self._models[record.serial] = model

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

    # ------------------------------------------------------------ wireless ADB

    def connect_wireless(self, address: str) -> str:
        """``adb connect host[:port]``; returns the confirmation text or raises OSError."""
        address = normalize_wireless_address(address)
        adb = self._adb()
        if adb is None:
            raise OSError("Android Platform Tools are not available.")
        try:
            result = self._command((str(adb), "connect", address), timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OSError(f"Could not reach {address}: {exc}") from exc
        message = (result.stdout + result.stderr).strip().splitlines()
        text = message[-1] if message else ""
        lowered = text.lower()
        if result.returncode == 0 and (
            lowered.startswith("connected to") or lowered.startswith("already connected")
        ):
            return text
        raise OSError(text or f"ADB could not connect to {address}.")

    def disconnect_wireless(self, address: str) -> str:
        """``adb disconnect host:port``; an empty address disconnects every TCP device."""
        address = normalize_wireless_address(address) if address.strip() else ""
        adb = self._adb()
        if adb is None:
            raise OSError("Android Platform Tools are not available.")
        try:
            arguments = (str(adb), "disconnect") + ((address,) if address else ())
            result = self._command(arguments, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OSError(f"Could not disconnect {address}: {exc}") from exc
        text = (result.stdout + result.stderr).strip()
        if result.returncode != 0 and "no such device" not in text.lower():
            raise OSError(text or f"ADB could not disconnect {address or 'wireless devices'}.")
        return text or f"Disconnected {address or 'all wireless devices'}."

    def enable_wireless(self, serial: str, *, port: int = 5555) -> str:
        """Switch a USB-attached headset to TCP/IP ADB and connect to it.

        Returns the ``host:port`` address that is now connected. The USB cable can be
        unplugged afterwards; the headset keeps listening until it reboots.
        """
        adb = self._adb()
        if adb is None:
            raise OSError("Android Platform Tools are not available.")
        if not serial:
            raise OSError("Connect the headset by USB first.")
        target = (str(adb), "-s", serial)
        try:
            ip_result = self._command(
                (*target, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"), timeout=15
            )
            address = parse_wlan_address(ip_result.stdout)
            if not address:
                route = self._command((*target, "shell", "ip", "route"), timeout=15)
                address = parse_route_source(route.stdout)
            if not address:
                raise OSError(
                    "The headset's Wi-Fi address could not be read. Make sure it is "
                    "connected to the same Wi-Fi network."
                )
            tcpip = self._command((*target, "tcpip", str(port)), timeout=20)
            if tcpip.returncode != 0:
                detail = (tcpip.stderr or tcpip.stdout).strip()
                raise OSError(detail or "ADB could not switch the headset to TCP/IP mode.")
        except subprocess.TimeoutExpired as exc:
            raise OSError(f"The headset did not answer in time: {exc}") from exc
        wireless = f"{address}:{port}"
        # The daemon restarts in TCP mode; give it a moment before connecting.
        import time

        last_error = ""
        for attempt in range(6):
            time.sleep(0.8 if attempt else 1.5)
            try:
                self.connect_wireless(wireless)
                return wireless
            except OSError as exc:
                last_error = str(exc)
        raise OSError(last_error or f"ADB could not connect to {wireless}.")

    def installed_apps(self, serial: str) -> tuple[InstalledQuestApp, ...]:
        """List third-party packages, using two bounded ADB calls for any library size."""
        adb = self._adb()
        if adb is None:
            raise OSError("Android Platform Tools are not available.")
        if not serial:
            raise OSError("No authorized Quest is selected.")
        target = (str(adb), "-s", serial, "shell")
        try:
            listed = self._command(
                (*target, "pm", "list", "packages", "-3", "--show-versioncode"),
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OSError(f"Installed apps could not be read: {exc}") from exc
        option_output = f"{listed.stdout}\n{listed.stderr}".casefold()
        show_version_unsupported = any(
            marker in option_output
            for marker in ("unknown option", "unsupported option", "unrecognized option")
        )
        if listed.returncode != 0 or show_version_unsupported:
            try:
                listed = self._command(
                    (*target, "pm", "list", "packages", "-3"),
                    timeout=15,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise OSError(f"Installed apps could not be read: {exc}") from exc
            if listed.returncode != 0:
                detail = (listed.stderr or listed.stdout).strip() or "ADB returned an error."
                raise OSError(f"Installed apps could not be read: {detail}")
        package_versions = parse_user_package_versions(listed.stdout)
        packages = tuple(sorted(package_versions, key=str.casefold))
        if not packages:
            return ()
        if all(package_versions[package] for package in packages):
            return tuple(
                InstalledQuestApp(package, package_versions[package])
                for package in packages
            )
        try:
            details = self._command(
                (*target, "dumpsys", "package", "packages"),
                timeout=25,
            )
        except (OSError, subprocess.TimeoutExpired):
            details = None
        versions = (
            parse_package_versions(details.stdout, set(packages))
            if details is not None and details.returncode == 0
            else {}
        )
        return tuple(
            InstalledQuestApp(package, *versions.get(package, ("", "")))
            for package in packages
        )
