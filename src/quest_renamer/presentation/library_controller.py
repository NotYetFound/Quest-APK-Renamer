"""QML-facing automatic game library with no required management workflow."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

from quest_renamer.domain.build import BuildResult
from quest_renamer.domain.installation import BundleInstallResult
from quest_renamer.domain.library import GameProfile, LibraryObb, profile_id
from quest_renamer.domain.models import BundleDraft, DeviceSnapshot, InstalledQuestApp
from quest_renamer.infrastructure.app_icons import cache_apk_icon, display_name_key
from quest_renamer.infrastructure.desktop_open import open_local_path
from quest_renamer.infrastructure.library_archive import (
    LibraryArchiveError,
    LibraryArchiveSummary,
    export_library_archive,
    import_library_archive,
    inspect_library_archive,
)
from quest_renamer.infrastructure.library_store import GameLibraryStore

ClipboardWriter = Callable[[str], bool]


def _write_system_clipboard(value: str) -> bool:
    if QGuiApplication.instance() is None:
        return False
    try:
        QGuiApplication.clipboard().setText(value)
    except RuntimeError:
        return False
    return True


class LibraryController(QObject):
    changed = Signal()
    # Fired only when the visible row list is rebuilt or the view switches, so the
    # QML ListView keeps its delegates (and scroll position) on selection changes.
    rowsChanged = Signal()
    activityMessage = Signal(str)
    inventoryReady = Signal(int, str, object, str)
    archiveReady = Signal(str, object, str)
    importConfirmationRequested = Signal(str)

    def __init__(
        self,
        store: GameLibraryStore,
        *,
        signing_root: Path,
        installed_apps: Callable[[str], tuple[InstalledQuestApp, ...]] | None = None,
        path_opener: Callable[[Path], bool] | None = None,
        clipboard_writer: ClipboardWriter | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._signing_root = signing_root
        self._icon_root = signing_root / "app-icons"
        self._installed_apps_reader = installed_apps
        self._path_opener = path_opener or open_local_path
        self._clipboard_writer = clipboard_writer or _write_system_clipboard
        self._profiles = store.load()
        self._apps: tuple[InstalledQuestApp, ...] = ()
        self._selected_profile_id = self._profiles[0].id if self._profiles else ""
        self._selected_package = ""
        self._show_installed = True
        self._user_chose_view = False
        self._connected = False
        self._device_serial = ""
        self._device_model = ""
        self._loaded_serial = ""
        self._loading = False
        self._error = ""
        self._action_text = ""
        self._archive_busy = False
        self._pending_archive: Path | None = None
        self._scan_generation = 0
        self._profiles_by_id: dict[str, GameProfile] = {}
        self._profiles_by_source: dict[str, tuple[GameProfile, ...]] = {}
        self._profiles_by_target: dict[str, tuple[GameProfile, ...]] = {}
        self._display_profiles: dict[str, GameProfile] = {}
        self._apps_by_package: dict[str, InstalledQuestApp] = {}
        self._key_health: dict[str, bool] = {}
        self._icons_by_name: dict[str, str] = {}
        self._saved_rows: list[dict[str, str | bool]] = []
        self._saved_rows_by_id: dict[str, dict[str, str | bool]] = {}
        self._installed_rows: list[dict[str, str | bool]] = []
        self._installed_rows_by_id: dict[str, dict[str, str | bool]] = {}
        self._refresh_profile_cache()
        self.inventoryReady.connect(self._apply_inventory)
        self.archiveReady.connect(self._apply_archive_result)

    @Property(list, notify=rowsChanged)
    def rows(self) -> list[dict[str, str | bool]]:
        return self._installed_rows if self._show_installed else self._saved_rows

    def _emit_rows(self) -> None:
        self.rowsChanged.emit()
        self.changed.emit()

    def key_ready(self, profile_id_value: str) -> bool:
        """Cached key health for a saved profile (no hashing on the caller's path)."""
        return self._key_health.get(profile_id_value, False)

    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._apps) if self._show_installed else len(self._profiles)

    @Property(bool, notify=changed)
    def isEmpty(self) -> bool:
        return not self._apps if self._show_installed else not self._profiles

    @Property(bool, notify=changed)
    def showInstalled(self) -> bool:
        return self._show_installed

    @Slot(bool)
    def setShowInstalled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._show_installed:
            return
        self._show_installed = enabled
        self._user_chose_view = True
        self._action_text = ""
        self._emit_rows()

    @Property(bool, notify=changed)
    def isConnected(self) -> bool:
        return self._connected

    @Property(bool, notify=changed)
    def isLoading(self) -> bool:
        return self._loading

    @Property(str, notify=changed)
    def errorMessage(self) -> str:
        return self._error

    @Property(str, notify=changed)
    def actionText(self) -> str:
        return self._action_text

    @Property(bool, notify=changed)
    def archiveBusy(self) -> bool:
        return self._archive_busy

    @Property(str, notify=changed)
    def deviceLabel(self) -> str:
        return self._device_model or "Quest"

    @Property(str, notify=changed)
    def statusText(self) -> str:
        if not self._show_installed:
            noun = "signing identity" if len(self._profiles) == 1 else "signing identities"
            return f"{len(self._profiles)} saved {noun}"
        if not self._connected:
            return "Connect and authorize a Quest to view its installed apps."
        if self._loading:
            return f"Reading apps from {self.deviceLabel}…"
        if self._error:
            return self._error
        if not self._apps:
            return f"No user-installed apps were found on {self.deviceLabel}."
        noun = "app" if len(self._apps) == 1 else "apps"
        return f"{len(self._apps)} user-installed {noun} on {self.deviceLabel}"

    @Property(str, notify=changed)
    def selectedId(self) -> str:
        return self._selected_package if self._show_installed else self._selected_profile_id

    @Property(dict, notify=changed)
    def selected(self) -> dict[str, str | bool]:
        rows = self._installed_rows_by_id if self._show_installed else self._saved_rows_by_id
        selected = self._selected_package if self._show_installed else self._selected_profile_id
        return rows.get(selected, {})

    @Property(str, constant=True)
    def libraryPath(self) -> str:
        return str(self._store.path)

    @Property(str, constant=True)
    def keyFolder(self) -> str:
        return str(self._signing_root)

    def profile(self, profile_id_value: str) -> GameProfile | None:
        return self._profiles_by_id.get(profile_id_value)

    def installed_app(self, package_name: str) -> InstalledQuestApp | None:
        return self._apps_by_package.get(package_name)

    def profile_for_installed(self, package_name: str) -> GameProfile | None:
        matches = tuple(
            profile
            for profile in self._profiles_by_target.get(package_name, ())
            if profile.target_package == package_name
            and (
                profile.original_package != profile.target_package
                or bool(profile.signing_keystore and profile.signing_metadata)
            )
        )
        if not matches:
            return None
        same_device = tuple(
            profile
            for profile in matches
            if profile.last_device_serial and profile.last_device_serial == self._device_serial
        )
        candidates = same_device or matches
        return max(candidates, key=lambda profile: profile.updated_utc)

    def display_profile_for_package(self, package_name: str) -> GameProfile | None:
        """Find cached display metadata without treating an original app as managed."""
        return self._display_profiles.get(package_name)

    def installed_version(self, package_name: str) -> str:
        app = self.installed_app(package_name)
        return app.version_code if app is not None else ""

    def profiles_for_source(self, original_package: str) -> tuple[GameProfile, ...]:
        return self._profiles_by_source.get(original_package, ())

    def profile_for_target(self, target_package: str) -> GameProfile | None:
        matches = self._profiles_by_target.get(target_package, ())
        return matches[0] if len(matches) == 1 else None

    def unique_profile_for_source(self, original_package: str) -> GameProfile | None:
        profiles = self.profiles_for_source(original_package)
        return profiles[0] if len(profiles) == 1 else None

    @Slot(str)
    def select(self, entry_id: str) -> None:
        if self._show_installed:
            if self.installed_app(entry_id) is None or entry_id == self._selected_package:
                return
            self._selected_package = entry_id
        else:
            if self.profile(entry_id) is None or entry_id == self._selected_profile_id:
                return
            self._selected_profile_id = entry_id
        self._action_text = ""
        self.changed.emit()

    @Slot(int)
    def selectOffset(self, offset: int) -> None:
        """Move the selection up or down by ``offset`` rows (keyboard navigation)."""
        rows = self._installed_rows if self._show_installed else self._saved_rows
        if not rows:
            return
        ids = [str(row["id"]) for row in rows]
        current = self._selected_package if self._show_installed else self._selected_profile_id
        index = ids.index(current) if current in ids else -1
        target = max(0, min(len(ids) - 1, index + offset if index >= 0 else 0))
        self.select(ids[target])

    @Slot(object)
    def setDevice(self, raw_snapshot: object) -> None:
        if not isinstance(raw_snapshot, DeviceSnapshot):
            return
        if not raw_snapshot.connected or not raw_snapshot.serial:
            changed = bool(
                self._connected
                or self._apps
                or self._loading
                or self._error
                or self._selected_package
            )
            self._scan_generation += 1
            self._connected = False
            # A fresh connection later may pick the live view again.
            self._user_chose_view = False
            self._device_serial = ""
            self._device_model = ""
            self._loaded_serial = ""
            self._apps = ()
            self._refresh_app_cache()
            self._selected_package = ""
            self._loading = False
            self._error = ""
            if changed:
                self._emit_rows()
            return
        new_device = raw_snapshot.serial != self._device_serial
        model_changed = raw_snapshot.model != self._device_model
        self._connected = True
        self._device_serial = raw_snapshot.serial
        self._device_model = raw_snapshot.model or "Quest"
        if new_device:
            self._scan_generation += 1
            self._loaded_serial = ""
            self._apps = ()
            self._refresh_app_cache()
            self._selected_package = ""
            self._loading = False
            self._error = ""
            if not self._user_chose_view:
                self._show_installed = True
        if new_device or model_changed:
            self._emit_rows()
        if new_device or self._loaded_serial != raw_snapshot.serial:
            self.refresh()

    @Slot()
    def refresh(self) -> None:
        if (
            not self._connected
            or not self._device_serial
            or self._loading
            or self._installed_apps_reader is None
        ):
            return
        self._scan_generation += 1
        generation = self._scan_generation
        serial = self._device_serial
        self._loading = True
        self._error = ""
        self.changed.emit()
        threading.Thread(
            target=self._inventory_worker,
            args=(generation, serial),
            daemon=True,
        ).start()

    def _inventory_worker(self, generation: int, serial: str) -> None:
        error = ""
        try:
            assert self._installed_apps_reader is not None
            apps = self._installed_apps_reader(serial)
        except OSError as exc:
            apps = ()
            error = str(exc)
        except Exception as exc:  # Keep an adapter failure out of the Qt event loop.
            apps = ()
            error = f"Installed apps could not be read: {exc}"
        self.inventoryReady.emit(generation, serial, apps, error)

    @Slot(int, str, object, str)
    def _apply_inventory(
        self,
        generation: int,
        serial: str,
        raw_apps: object,
        error: str,
    ) -> None:
        if generation != self._scan_generation or serial != self._device_serial:
            return
        apps = (
            tuple(item for item in raw_apps if isinstance(item, InstalledQuestApp))
            if isinstance(raw_apps, (tuple, list))
            else ()
        )
        self._loading = False
        self._error = error
        if not error:
            self._apps = tuple(sorted(apps, key=lambda app: app.package_name.casefold()))
            self._refresh_app_cache()
            self._loaded_serial = serial
            if self.installed_app(self._selected_package) is None:
                self._selected_package = self._apps[0].package_name if self._apps else ""
            self.activityMessage.emit(
                f"Library refreshed: {len(self._apps)} user-installed app"
                f"{'s' if len(self._apps) != 1 else ''} found on {self.deviceLabel}."
            )
        self._emit_rows()

    @Slot()
    def openKeyFolder(self) -> None:
        self._signing_root.mkdir(parents=True, exist_ok=True)
        if self._path_opener(self._signing_root):
            return
        self.activityMessage.emit(f"Could not open signing-key folder: {self._signing_root}")

    @Slot()
    def openLibraryFolder(self) -> None:
        self._store.path.parent.mkdir(parents=True, exist_ok=True)
        if self._path_opener(self._store.path.parent):
            return
        self.activityMessage.emit(f"Could not open library folder: {self._store.path.parent}")

    @Slot()
    def openSelectedKeyFolder(self) -> None:
        profile = self.profile(self._selected_profile_id)
        if profile is None:
            self._set_action("Select a saved identity first.")
            return
        candidates = tuple(
            Path(value).parent
            for value in (profile.signing_keystore, profile.signing_metadata)
            if value
        )
        folder = next((path for path in candidates if path.is_dir()), None)
        if folder is None:
            self._set_action("The saved key folder is missing.")
            return
        if self._path_opener(folder):
            self._set_action(f"Opened the key folder for {profile.game_name}.")
            return
        self._set_action(f"Could not open the key folder: {folder}")

    @Slot()
    def copySelectedInformation(self) -> None:
        profile = self.profile(self._selected_profile_id)
        if profile is None:
            self._set_action("Select a saved identity first.")
            return
        self._copy_profiles((profile,), f"Copied all information for {profile.game_name}.")

    @Slot()
    def copyAllInformation(self) -> None:
        if not self._profiles:
            self._set_action("There are no saved identities to copy.")
            return
        self._copy_profiles(
            self._profiles,
            f"Copied all information for {len(self._profiles)} saved identities.",
        )

    def _copy_profiles(self, profiles: tuple[GameProfile, ...], message: str) -> None:
        text = (
            "Quest APK Renamer saved signing identities\n"
            f"Count: {len(profiles)}\n\n"
            + "\n\n".join(self._profile_information(profile) for profile in profiles)
        )
        if not self._clipboard_writer(text):
            self._set_action("The clipboard is unavailable in this session.")
            return
        self._set_action(message)
        self.activityMessage.emit(message)

    @staticmethod
    def _profile_information(profile: GameProfile) -> str:
        lines = [
            profile.game_name,
            f"Saved identity ID: {profile.id}",
            f"Original package: {profile.original_package}",
            f"Renamed package: {profile.target_package}",
            f"Source version: {profile.source_version or 'Not recorded'}",
            f"Source signer: {profile.source_signer_id or 'Not recorded'}",
            f"Installed version: {profile.installed_version or 'Not recorded'}",
            f"Source folder: {profile.source_path or 'Not recorded'}",
            f"Last output: {profile.output_path or 'Not recorded'}",
            f"Signing key: {profile.signing_keystore or 'Not saved'}",
            f"Signing metadata: {profile.signing_metadata or 'Not saved'}",
            f"Key SHA-256: {profile.signing_key_sha256 or 'Not recorded'}",
            f"Cached icon: {profile.app_icon or 'Not saved'}",
            f"Patches: {', '.join(profile.patches) if profile.patches else 'None'}",
            f"Last Quest serial: {profile.last_device_serial or 'Not recorded'}",
            f"Created: {profile.created_utc or 'Not recorded'}",
            f"Updated: {profile.updated_utc or 'Not recorded'}",
        ]
        if profile.obbs:
            lines.append("OBB files:")
            lines.extend(
                f"  - {obb.name} ({obb.size} bytes)"
                + (f" SHA-256 {obb.sha256}" if obb.sha256 else "")
                for obb in profile.obbs
            )
        else:
            lines.append("OBB files: None recorded")
        metadata = Path(profile.signing_metadata) if profile.signing_metadata else None
        if metadata is not None:
            try:
                if metadata.is_file() and metadata.stat().st_size <= 64 * 1024:
                    payload = json.loads(metadata.read_text(encoding="utf-8"))
                    lines.extend(
                        (
                            "Signing metadata JSON:",
                            json.dumps(payload, indent=2, ensure_ascii=False),
                        )
                    )
            except (OSError, json.JSONDecodeError):
                lines.append("Signing metadata JSON: Could not be read")
        return "\n".join(lines)

    @Slot(QUrl)
    def exportSelected(self, url: QUrl) -> None:
        profile = self.profile(self._selected_profile_id)
        if profile is None:
            self._set_action("Select a saved identity first.")
            return
        self._start_archive_export(Path(url.toLocalFile()), (profile,))

    @Slot(QUrl)
    def exportAll(self, url: QUrl) -> None:
        if not self._profiles:
            self._set_action("There are no saved identities to export.")
            return
        self._start_archive_export(Path(url.toLocalFile()), self._profiles)

    def _start_archive_export(
        self,
        destination: Path,
        profiles: tuple[GameProfile, ...],
    ) -> None:
        if self._archive_busy:
            return
        self._archive_busy = True
        self._action_text = "Creating the private Library archive…"
        self.changed.emit()

        def worker() -> None:
            try:
                result: object = export_library_archive(destination, profiles)
                error = ""
            except Exception as exc:  # busy flag must always clear
                result = None
                error = str(exc) if isinstance(exc, (LibraryArchiveError, OSError)) else (
                    f"The archive could not be created: {exc}"
                )
            self.archiveReady.emit("export", result, error)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(QUrl)
    def prepareImport(self, url: QUrl) -> None:
        if self._archive_busy:
            return
        source = Path(url.toLocalFile())
        existing_ids = set(self._profiles_by_id)
        self._pending_archive = source
        self._archive_busy = True
        self._action_text = "Checking the Library archive…"
        self.changed.emit()

        def worker() -> None:
            try:
                result: object = inspect_library_archive(
                    source,
                    existing_ids,
                )
                error = ""
            except Exception as exc:  # busy flag must always clear
                result = None
                error = str(exc) if isinstance(exc, (LibraryArchiveError, OSError)) else (
                    f"The archive could not be checked: {exc}"
                )
            self.archiveReady.emit("inspect", result, error)

        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def confirmImport(self) -> None:
        source = self._pending_archive
        if source is None or self._archive_busy:
            return
        self._pending_archive = None
        self._archive_busy = True
        self._action_text = "Importing saved identities and private keys…"
        self.changed.emit()

        def worker() -> None:
            try:
                result: object = import_library_archive(source, self._signing_root)
                error = ""
            except Exception as exc:  # busy flag must always clear
                result = None
                error = str(exc) if isinstance(exc, (LibraryArchiveError, OSError)) else (
                    f"The archive could not be imported: {exc}"
                )
            self.archiveReady.emit("import", result, error)

        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def cancelImport(self) -> None:
        if self._archive_busy:
            return
        self._pending_archive = None
        self._set_action("Import cancelled.")

    @Slot()
    def deleteSelected(self) -> None:
        profile = self.profile(self._selected_profile_id)
        if profile is None or self._archive_busy:
            return
        self._profiles = self._store.forget(profile.id)
        self._selected_profile_id = self._profiles[0].id if self._profiles else ""
        self._refresh_profile_cache()
        self._action_text = (
            f"Removed {profile.game_name} from the vault. Its key files were kept."
        )
        self._emit_rows()
        self.activityMessage.emit(f"Saved identity removed from Library: {profile.game_name}")

    @Slot(str, object, str)
    def _apply_archive_result(
        self,
        operation: str,
        raw_result: object,
        error: str,
    ) -> None:
        self._archive_busy = False
        if error:
            self._pending_archive = None
            self._action_text = error
            self.changed.emit()
            self.activityMessage.emit(f"Library archive error: {error}")
            return
        if operation == "inspect" and isinstance(raw_result, LibraryArchiveSummary):
            summary = raw_result
            noun = "identity" if summary.count == 1 else "identities"
            replacement = (
                f" {summary.replacements} existing "
                f"{'entry' if summary.replacements == 1 else 'entries'} will be replaced."
                if summary.replacements
                else ""
            )
            key_detail = (
                f"{summary.complete_keys} include complete signing keys."
                if summary.complete_keys
                else "No complete signing keys are included."
            )
            self._action_text = "Archive checked and ready to import."
            self.changed.emit()
            self.importConfirmationRequested.emit(
                f"Import {summary.count} saved {noun}?{replacement}\n\n{key_detail} "
                "Included private files will be copied into this app's data folder."
            )
            return
        if operation == "export" and isinstance(raw_result, Path):
            self._action_text = f"Private Library archive saved to {raw_result}."
            self.changed.emit()
            self.activityMessage.emit(f"Library archive exported: {raw_result}")
            return
        if operation == "import" and isinstance(raw_result, tuple):
            imported = tuple(
                item for item in raw_result if isinstance(item, GameProfile)
            )
            by_id = {profile.id: profile for profile in self._profiles}
            by_id.update({profile.id: profile for profile in imported})
            merged = tuple(
                sorted(by_id.values(), key=lambda item: item.updated_utc, reverse=True)
            )
            try:
                self._store.save(merged)
            except OSError as exc:
                self._action_text = (
                    "Imported keys were preserved, but Library saving failed: "
                    f"{exc}"
                )
                self.changed.emit()
                self.activityMessage.emit(self._action_text)
                return
            self._profiles = merged
            self._selected_profile_id = imported[0].id if imported else ""
            self._show_installed = False
            self._refresh_profile_cache()
            self._action_text = (
                f"Imported {len(imported)} saved "
                f"{'identity' if len(imported) == 1 else 'identities'}."
            )
            self._emit_rows()
            self.activityMessage.emit(self._action_text)

    def _set_action(self, message: str) -> None:
        self._action_text = message
        self.changed.emit()

    @Slot()
    def refreshKeyHealth(self) -> None:
        """Recheck saved key files after backup/restore or an external file change."""
        self._refresh_profile_cache()
        self._emit_rows()

    def record_build(
        self,
        source: BundleDraft,
        target_package: str,
        result: BuildResult,
        patches: tuple[str, ...],
    ) -> GameProfile:
        identity = profile_id(source.package_name, target_package)
        current = self.profile(identity)
        game_name = result.app_label or source.game_name or target_package
        values: dict[str, Any] = {
            "game_name": game_name,
            "source_path": str(source.root),
            "output_path": str(result.output_root),
            "source_version": source.version_code,
            "source_signer_id": (
                source.signer_identity.id if source.signer_identity is not None else ""
            ),
            "patches": patches,
        }
        icon = result.app_icon or cache_apk_icon(source.apk, game_name, self._icon_root)
        if icon is not None:
            values["app_icon"] = str(icon)
        if result.signing_keystore is not None:
            values["signing_keystore"] = str(result.signing_keystore)
        if result.signing_metadata is not None:
            values["signing_metadata"] = str(result.signing_metadata)
        if result.signing_key_sha256:
            values["signing_key_sha256"] = result.signing_key_sha256
        if current is None:
            profile = GameProfile.create(
                original_package=source.package_name,
                target_package=target_package,
                installed_version="",
                **values,
            )
        else:
            profile = current.updated(**values)
        self._replace(profile)
        return profile

    def record_install(
        self,
        bundle: BundleDraft,
        result: BundleInstallResult,
        serial: str,
        *,
        original_package: str = "",
    ) -> GameProfile | None:
        current = next(iter(self._profiles_by_target.get(result.package_name, ())), None)
        original = original_package or (
            current.original_package if current is not None else result.package_name
        )
        obbs = tuple(LibraryObb(item.source.name, item.size) for item in result.obbs)
        game_name = (
            current.game_name
            if current is not None
            else bundle.game_name or result.package_name
        )
        values: dict[str, Any] = {
            "game_name": game_name,
            "output_path": str(bundle.root),
            "installed_version": bundle.version_code,
            "obbs": obbs,
            "last_device_serial": serial,
        }
        current_icon = (
            Path(current.app_icon) if current is not None and current.app_icon else None
        )
        icon = (
            current_icon
            if current_icon is not None and current_icon.is_file()
            else cache_apk_icon(bundle.apk, game_name, self._icon_root)
        )
        if icon is not None:
            values["app_icon"] = str(icon)
        profile: GameProfile | None
        if current is None and original == result.package_name:
            # A normal headset app keeps its publisher signature. It belongs in
            # the live inventory, not in the local signing-key vault.
            profile = None
        elif current is None:
            profile = GameProfile.create(
                original_package=original,
                target_package=result.package_name,
                source_version=bundle.version_code,
                **values,
            )
        else:
            profile = current.updated(**values)
        if profile is not None:
            self._replace(profile)
        if self._connected:
            replacement = InstalledQuestApp(
                result.package_name,
                bundle.version_code,
                app_name=game_name,
                icon_path=str(icon) if icon is not None else "",
            )
            found = False
            updated_apps: list[InstalledQuestApp] = []
            for app in self._apps:
                if app.package_name == result.package_name:
                    updated_apps.append(replacement)
                    found = True
                else:
                    updated_apps.append(app)
            if not found:
                updated_apps.append(replacement)
            self._apps = tuple(
                sorted(updated_apps, key=lambda app: app.package_name.casefold())
            )
            self._refresh_app_cache()
            self._selected_package = result.package_name
            self._emit_rows()
        return profile

    def _replace(self, profile: GameProfile) -> None:
        self._profiles = self._store.upsert(profile)
        self._refresh_profile_cache()
        self._selected_profile_id = profile.id
        if self.installed_app(profile.target_package) is not None:
            self._selected_package = profile.target_package
        self._emit_rows()

    def _installed_row(self, app: InstalledQuestApp) -> dict[str, str | bool]:
        profile = self.profile_for_installed(app.package_name)
        display_profile = profile or self.display_profile_for_package(app.package_name)
        managed = profile is not None
        key_ready = bool(profile and self._key_health.get(profile.id, False))
        if managed and key_ready:
            key_status = "Saved signing key ready"
        elif managed:
            key_status = "Saved signing key needs attention"
        else:
            key_status = "Original signature required"
        if app.version_name and app.version_code:
            version_text = f"{app.version_name}  (code {app.version_code})"
        elif app.version_name:
            version_text = app.version_name
        elif app.version_code:
            version_text = f"Version code {app.version_code}"
        else:
            version_text = "Version not reported"
        game_name = (
            display_profile.game_name
            if display_profile is not None
            else app.app_name or app.package_name
        )
        icon_path = (
            display_profile.app_icon
            if display_profile is not None and display_profile.app_icon
            else app.icon_path
        )
        icon_path = self._shared_icon_path(game_name, icon_path)
        return {
            "id": app.package_name,
            "profileId": profile.id if profile is not None else "",
            "gameName": game_name,
            "iconUrl": self._icon_url(icon_path),
            "originalPackage": profile.original_package if profile else app.package_name,
            "targetPackage": app.package_name,
            "identity": app.package_name,
            "version": app.version_code,
            "versionName": app.version_name,
            "versionText": version_text,
            "sourcePath": profile.source_path if profile else "",
            "outputPath": profile.output_path if profile else "",
            "keyStatus": key_status,
            "keyReady": key_ready,
            "keyPath": profile.signing_keystore if profile else "",
            "metadataPath": profile.signing_metadata if profile else "",
            "keySha256": profile.signing_key_sha256 if profile else "",
            "installed": True,
            "managed": managed,
            "status": "Saved identity" if managed else "Direct update",
            "updateHelp": (
                "The saved app ID and signing key will be reused automatically."
                if managed
                else "Choose an update with this exact package ID and its original signature."
            ),
            "selected": False,
        }

    @staticmethod
    def _icon_url(path: str) -> str:
        return QUrl.fromLocalFile(path).toString() if path else ""

    def _shared_icon_path(self, game_name: str, preferred: str = "") -> str:
        key = display_name_key(game_name)
        cached = self._icons_by_name.get(key, "")
        if preferred and preferred == cached:
            return preferred
        if preferred and Path(preferred).is_file():
            return preferred
        return cached

    def _saved_row(self, profile: GameProfile) -> dict[str, str | bool]:
        key_ready = self._key_health.get(profile.id, False)
        key_status = "Key ready" if key_ready else "Key missing or changed"
        if not profile.signing_keystore and not profile.signing_metadata:
            key_status = "No saved key"
        status = (
            "Ready"
            if key_ready
            else "No key"
            if not profile.signing_keystore and not profile.signing_metadata
            else "Needs attention"
        )
        return {
            "id": profile.id,
            "profileId": profile.id,
            "gameName": profile.game_name,
            "iconUrl": self._icon_url(
                self._shared_icon_path(profile.game_name, profile.app_icon)
            ),
            "originalPackage": profile.original_package,
            "targetPackage": profile.target_package,
            "identity": f"{profile.original_package}  →  {profile.target_package}",
            "version": "",
            "versionName": "",
            "versionText": (
                f"Key SHA-256 {profile.signing_key_sha256[:12]}…"
                if profile.signing_key_sha256
                else ""
            ),
            "sourcePath": profile.source_path,
            "outputPath": profile.output_path,
            "keyStatus": key_status,
            "keyReady": key_ready,
            "keyPath": profile.signing_keystore,
            "metadataPath": profile.signing_metadata,
            "keySha256": profile.signing_key_sha256,
            "installed": False,
            "managed": True,
            "status": status,
            "updateHelp": "",
            "selected": False,
        }

    def _refresh_profile_cache(self) -> None:
        by_source: dict[str, list[GameProfile]] = {}
        by_target: dict[str, list[GameProfile]] = {}
        display_profiles: dict[str, GameProfile] = {}
        key_health: dict[str, bool] = {}
        icons: dict[str, str] = {}
        for profile in self._profiles:
            by_source.setdefault(profile.original_package, []).append(profile)
            by_target.setdefault(profile.target_package, []).append(profile)
            key_health[profile.id] = profile.key_available
            for package in {profile.original_package, profile.target_package}:
                current = display_profiles.get(package)
                if current is None or profile.updated_utc > current.updated_utc:
                    display_profiles[package] = profile
            if profile.app_icon and Path(profile.app_icon).is_file():
                icons[display_name_key(profile.game_name)] = profile.app_icon
        self._profiles_by_id = {profile.id: profile for profile in self._profiles}
        self._profiles_by_source = {
            package: tuple(profiles) for package, profiles in by_source.items()
        }
        self._profiles_by_target = {
            package: tuple(profiles) for package, profiles in by_target.items()
        }
        self._display_profiles = display_profiles
        self._key_health = key_health
        self._icons_by_name = icons
        self._saved_rows = [self._saved_row(profile) for profile in self._profiles]
        self._saved_rows_by_id = {str(row["id"]): row for row in self._saved_rows}
        self._refresh_app_cache()

    def _refresh_app_cache(self) -> None:
        self._apps_by_package = {app.package_name: app for app in self._apps}
        self._installed_rows = [self._installed_row(app) for app in self._apps]
        self._installed_rows_by_id = {
            str(row["id"]): row for row in self._installed_rows
        }
