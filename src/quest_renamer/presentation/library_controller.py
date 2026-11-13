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
from quest_renamer.domain.library import (
    GameProfile,
    LibraryObb,
    QuestIdentityRecord,
    profile_id,
)
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
from quest_renamer.infrastructure.quest_identity_store import QuestIdentityStore

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
    identityOperationReady = Signal(str, object, str)
    importConfirmationRequested = Signal(str)

    def __init__(
        self,
        store: GameLibraryStore,
        *,
        signing_root: Path,
        installed_apps: Callable[[str], tuple[InstalledQuestApp, ...]] | None = None,
        device_identities: QuestIdentityStore | None = None,
        path_opener: Callable[[Path], bool] | None = None,
        clipboard_writer: ClipboardWriter | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._signing_root = signing_root
        self._icon_root = signing_root / "app-icons"
        self._installed_apps_reader = installed_apps
        self._device_identities = device_identities
        self._path_opener = path_opener or open_local_path
        self._clipboard_writer = clipboard_writer or _write_system_clipboard
        self._local_profiles = store.load()
        self._device_profiles: tuple[GameProfile, ...] = ()
        self._session_profiles: dict[str, GameProfile] = {}
        # Old desktop profiles are migration candidates, not a second Library.
        # They become active only when their renamed package is installed on the
        # currently connected headset.
        self._profiles: tuple[GameProfile, ...] = ()
        self._apps: tuple[InstalledQuestApp, ...] = ()
        self._selected_profile_id = ""
        self._selected_package = ""
        self._show_installed = True
        self._connected = False
        self._device_serial = ""
        self._device_model = ""
        self._loaded_serial = ""
        self._loading = False
        self._error = ""
        self._action_text = ""
        self._failed_action = ""
        self._archive_busy = False
        self._identity_operations = 0
        self._pending_archive: Path | None = None
        self._scan_generation = 0
        self._profiles_by_id: dict[str, GameProfile] = {}
        self._profiles_by_source: dict[str, tuple[GameProfile, ...]] = {}
        self._profiles_by_target: dict[str, tuple[GameProfile, ...]] = {}
        self._display_profiles: dict[str, GameProfile] = {}
        self._apps_by_package: dict[str, InstalledQuestApp] = {}
        self._key_health: dict[str, bool] = {}
        self._identity_errors: dict[str, str] = {}
        self._icons_by_name: dict[str, str] = {}
        self._installed_rows: list[dict[str, str | bool]] = []
        self._installed_rows_by_id: dict[str, dict[str, str | bool]] = {}
        self._refresh_profile_cache()
        self.inventoryReady.connect(self._apply_inventory)
        self.archiveReady.connect(self._apply_archive_result)
        self.identityOperationReady.connect(self._apply_identity_operation)

    @Property(list, notify=rowsChanged)
    def rows(self) -> list[dict[str, str | bool]]:
        return self._installed_rows

    def _emit_rows(self) -> None:
        self.rowsChanged.emit()
        self.changed.emit()

    def key_ready(self, profile_id_value: str) -> bool:
        """Cached key health for a saved profile (no hashing on the caller's path)."""
        return self._key_health.get(profile_id_value, False)

    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._apps)

    @Property(bool, notify=changed)
    def isEmpty(self) -> bool:
        return not self._apps

    @Property(bool, notify=changed)
    def showInstalled(self) -> bool:
        return True

    @Slot(bool)
    def setShowInstalled(self, enabled: bool) -> None:
        # Kept as a compatibility no-op for older QML/tests. Library is now a
        # connected-headset view; private identities are not a second UI mode.
        del enabled

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
    def actionFailed(self) -> bool:
        return bool(self._action_text) and self._action_text == self._failed_action

    @Property(bool, notify=changed)
    def archiveBusy(self) -> bool:
        return self._archive_busy or self._identity_operations > 0

    @Property(str, notify=changed)
    def deviceLabel(self) -> str:
        return self._device_model or "Quest"

    @Property(str, notify=changed)
    def statusText(self) -> str:
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
        return self._selected_package

    @Property(dict, notify=changed)
    def selected(self) -> dict[str, str | bool]:
        return self._installed_rows_by_id.get(self._selected_package, {})

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

    def identity_error(self, package_name: str) -> str:
        return self._identity_errors.get(package_name, "")

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
        if self.installed_app(entry_id) is None or entry_id == self._selected_package:
            return
        self._selected_package = entry_id
        self._action_text = ""
        self.changed.emit()

    @Slot(int)
    def selectOffset(self, offset: int) -> None:
        """Move the selection up or down by ``offset`` rows (keyboard navigation)."""
        rows = self._installed_rows
        if not rows:
            return
        ids = [str(row["id"]) for row in rows]
        current = self._selected_package
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
            self._device_serial = ""
            self._device_model = ""
            self._loaded_serial = ""
            self._apps = ()
            self._device_profiles = ()
            self._identity_errors = {}
            self._rebuild_profiles()
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
            self._device_profiles = ()
            self._identity_errors = {}
            self._rebuild_profiles()
            self._selected_package = ""
            self._loading = False
            self._error = ""
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
            identities = (
                self._device_identities.load(
                    serial,
                    {app.package_name for app in apps},
                )
                if self._device_identities is not None
                else ()
            )
        except OSError as exc:
            apps = ()
            identities = ()
            error = str(exc)
        except Exception as exc:  # Keep an adapter failure out of the Qt event loop.
            apps = ()
            identities = ()
            error = f"Installed apps could not be read: {exc}"
        self.inventoryReady.emit(generation, serial, (apps, identities), error)

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
        raw_inventory: object = ()
        raw_identities: object = ()
        if isinstance(raw_apps, tuple) and len(raw_apps) == 2:
            raw_inventory, raw_identities = raw_apps
        else:
            raw_inventory = raw_apps
        apps = (
            tuple(item for item in raw_inventory if isinstance(item, InstalledQuestApp))
            if isinstance(raw_inventory, (tuple, list))
            else ()
        )
        identities = (
            tuple(item for item in raw_identities if isinstance(item, QuestIdentityRecord))
            if isinstance(raw_identities, (tuple, list))
            else ()
        )
        self._loading = False
        self._error = error
        if not error:
            self._apps = tuple(sorted(apps, key=lambda app: app.package_name.casefold()))
            self._device_profiles = tuple(
                record.profile for record in identities if record.profile is not None
            )
            self._identity_errors = {
                record.package_name: record.error for record in identities if record.error
            }
            self._rebuild_profiles()
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
        profile = self.profile_for_installed(self._selected_package)
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
        profile = self.profile_for_installed(self._selected_package)
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
        if self.archiveBusy:
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
        if self.archiveBusy:
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
        if (
            source is None
            or self.archiveBusy
            or not self._connected
            or not self._selected_package
        ):
            return
        self._pending_archive = None
        self._archive_busy = True
        self._action_text = "Importing saved identities and private keys…"
        self.changed.emit()

        def worker() -> None:
            try:
                import_root = (
                    self._device_identities.cache_root / "imports"
                    if self._device_identities is not None
                    else self._signing_root / "imported-identities"
                )
                result: object = import_library_archive(source, import_root)
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
        if self.archiveBusy:
            return
        self._pending_archive = None
        self._set_action("Import cancelled.")

    @Slot()
    def deleteSelected(self) -> None:
        package_name = self._selected_package
        profile = self.profile_for_installed(package_name)
        if (
            self.archiveBusy
            or self._device_identities is None
            or not self._device_serial
            or (profile is None and package_name not in self._identity_errors)
        ):
            self._set_action("This app has no QAPKR identity stored on the connected Quest.")
            return
        row = self._installed_rows_by_id.get(package_name, {})
        game_name = str(row.get("gameName") or package_name)
        self._archive_busy = True
        self._action_text = f"Removing the QAPKR identity for {game_name}…"
        self.changed.emit()
        serial = self._device_serial

        def worker() -> None:
            try:
                assert self._device_identities is not None
                self._device_identities.delete(serial, package_name)
                error = ""
            except Exception as exc:
                error = f"The identity could not be removed from the Quest: {exc}"
            self.identityOperationReady.emit(
                "delete",
                (profile if profile is not None else package_name, serial),
                error,
            )

        threading.Thread(target=worker, daemon=True).start()

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
            self._failed_action = error
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
            if len(imported) != 1:
                self._action_text = "Choose an archive containing exactly one app identity."
                self.changed.emit()
                self.activityMessage.emit(self._action_text)
                return
            profile = imported[0]
            if profile.target_package != self._selected_package:
                self._action_text = (
                    "That identity belongs to a different app ID: "
                    f"{profile.target_package}."
                )
                self.changed.emit()
                self.activityMessage.emit(self._action_text)
                return
            self._session_profiles[profile.id] = profile
            self._selected_profile_id = profile.id
            self._rebuild_profiles()
            self._emit_rows()
            self._store_identity_on_quest(profile, self._device_serial)

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
        if current is None:
            current = self._pending_profile_for_bundle(bundle, result.package_name)
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
            self._store_identity_on_quest(profile, serial)
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

    def _pending_profile_for_bundle(
        self,
        bundle: BundleDraft,
        target_package: str,
    ) -> GameProfile | None:
        """Recover a build's local key after an app restart.

        Pending build identities stay out of the connected-headset Library until
        their package is installed. A finished folder can still be installed
        after restarting QAPKR, so bind it to the pending identity using its
        exact output path or the build report shipped in that folder.
        """
        candidates = tuple(
            profile
            for profile in self._local_profiles
            if profile.target_package == target_package and profile.key_available
        )
        if not candidates:
            return None
        try:
            bundle_root = bundle.root.resolve()
            exact = tuple(
                profile
                for profile in candidates
                if profile.output_path
                and Path(profile.output_path).expanduser().resolve() == bundle_root
            )
        except OSError:
            exact = ()
        if len(exact) == 1:
            return exact[0]

        packages = self._build_report_packages(bundle.root)
        if packages is None or packages[1] != target_package:
            return None
        original_package = packages[0]
        matches = tuple(
            profile
            for profile in candidates
            if profile.original_package == original_package
        )
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _build_report_packages(root: Path) -> tuple[str, str] | None:
        for name in ("quest-renamer-report.json", "RENAME-REPORT.json"):
            path = root / name
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            packages = payload.get("packages")
            if not isinstance(packages, dict):
                continue
            source = packages.get("source")
            output = packages.get("output")
            if isinstance(source, str) and source and isinstance(output, str) and output:
                return source, output
        return None

    def _replace(self, profile: GameProfile) -> None:
        self._local_profiles = self._store.upsert(profile)
        self._session_profiles[profile.id] = profile
        self._rebuild_profiles()
        self._selected_profile_id = profile.id
        if self.installed_app(profile.target_package) is not None:
            self._selected_package = profile.target_package
        self._emit_rows()

    def _store_identity_on_quest(self, profile: GameProfile, serial: str) -> None:
        if self._device_identities is None or not serial or not profile.key_available:
            return
        self._identity_operations += 1
        self._action_text = f"Saving {profile.game_name}'s update key on the Quest…"
        self.changed.emit()

        def worker() -> None:
            try:
                assert self._device_identities is not None
                self._device_identities.save(serial, profile)
                error = ""
            except Exception as exc:
                error = (
                    "The app installed, but its update key could not be saved on "
                    f"the Quest: {exc}"
                )
            self.identityOperationReady.emit("save", (profile, serial), error)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(str, object, str)
    def _apply_identity_operation(
        self,
        operation: str,
        raw_profile: object,
        error: str,
    ) -> None:
        if operation == "save":
            self._identity_operations = max(0, self._identity_operations - 1)
        else:
            self._archive_busy = False
        operation_serial = self._device_serial
        package_name = ""
        if (
            isinstance(raw_profile, tuple)
            and len(raw_profile) == 2
            and isinstance(raw_profile[0], (GameProfile, str))
            and isinstance(raw_profile[1], str)
        ):
            identity_value, operation_serial = raw_profile
            profile = identity_value if isinstance(identity_value, GameProfile) else None
            package_name = (
                identity_value.target_package
                if isinstance(identity_value, GameProfile)
                else identity_value
            )
        elif isinstance(raw_profile, GameProfile):
            profile = raw_profile
            package_name = profile.target_package
        else:
            return
        if operation_serial != self._device_serial:
            self._action_text = (
                "The identity operation finished on the previous headset. "
                "Reconnect it to refresh the result."
            )
            self.changed.emit()
            return
        if error:
            self._action_text = error
            self._failed_action = error
            self.changed.emit()
            self.activityMessage.emit(error)
            return
        if operation == "save":
            if profile is None:
                return
            # Keep a session copy for installing the same renamed app on another
            # headset, but retire the old computer-side durable vault entry.
            remaining = tuple(
                item for item in self._device_profiles if item.id != profile.id
            )
            self._device_profiles = (*remaining, profile)
            self._identity_errors.pop(profile.target_package, None)
            self._local_profiles = self._store.forget(profile.id)
            self._rebuild_profiles()
            self._action_text = f"Update key saved on {self.deviceLabel}."
            self.activityMessage.emit(
                f"QAPKR identity stored on {self.deviceLabel}: {profile.target_package}"
            )
        elif operation == "delete":
            self._device_profiles = tuple(
                item
                for item in self._device_profiles
                if item.target_package != package_name
            )
            self._session_profiles = {
                identity: item
                for identity, item in self._session_profiles.items()
                if item.target_package != package_name
            }
            self._identity_errors.pop(package_name, None)
            self._rebuild_profiles()
            game_name = profile.game_name if profile is not None else package_name
            self._action_text = (
                f"Removed {game_name}'s QAPKR identity from {self.deviceLabel}."
            )
            self.activityMessage.emit(self._action_text)
        self._emit_rows()

    def _rebuild_profiles(self) -> None:
        """Combine device identities with only useful migration/session records."""
        installed = {app.package_name for app in self._apps}
        local_migrations = (
            profile
            for profile in self._local_profiles
            if profile.target_package in installed
        )
        by_id = {profile.id: profile for profile in local_migrations}
        by_id.update(self._session_profiles)
        # A verified headset identity always wins over an older local migration.
        by_id.update({profile.id: profile for profile in self._device_profiles})
        self._profiles = tuple(
            sorted(by_id.values(), key=lambda item: item.updated_utc, reverse=True)
        )
        self._refresh_profile_cache()

    def _installed_row(self, app: InstalledQuestApp) -> dict[str, str | bool]:
        profile = self.profile_for_installed(app.package_name)
        display_profile = profile or self.display_profile_for_package(app.package_name)
        identity_error = self._identity_errors.get(app.package_name, "")
        managed = profile is not None or bool(identity_error)
        key_ready = bool(profile and self._key_health.get(profile.id, False))
        device_profile_ids = {item.id for item in self._device_profiles}
        stored_on_quest = bool(profile and profile.id in device_profile_ids)
        if identity_error:
            key_status = "Quest key needs attention"
        elif managed and key_ready and stored_on_quest:
            key_status = "Update key ready on Quest"
        elif managed and key_ready:
            key_status = "Local key ready to migrate"
        elif managed:
            key_status = "Update key needs attention"
        else:
            key_status = "Publisher-signed"
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
            "status": (
                "Key issue"
                if identity_error
                else "Managed"
                if managed
                else "Direct update"
            ),
            "identityError": identity_error,
            "storedOnQuest": stored_on_quest,
            "updateHelp": (
                identity_error
                if identity_error
                else "The app will be rebuilt with the update key stored on this Quest."
                if stored_on_quest
                else "The existing update key will move to this Quest after a verified install."
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
        self._refresh_app_cache()

    def _refresh_app_cache(self) -> None:
        self._apps_by_package = {app.package_name: app for app in self._apps}
        self._installed_rows = [self._installed_row(app) for app in self._apps]
        self._installed_rows_by_id = {
            str(row["id"]): row for row in self._installed_rows
        }
