"""QML-facing automatic game library with no required management workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from quest_renamer.domain.build import BuildResult
from quest_renamer.domain.installation import BundleInstallResult
from quest_renamer.domain.library import GameProfile, LibraryObb, profile_id
from quest_renamer.domain.models import BundleDraft
from quest_renamer.infrastructure.desktop_open import open_local_path
from quest_renamer.infrastructure.library_store import GameLibraryStore


class LibraryController(QObject):
    changed = Signal()
    activityMessage = Signal(str)

    def __init__(
        self,
        store: GameLibraryStore,
        *,
        signing_root: Path,
        path_opener: Callable[[Path], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._signing_root = signing_root
        self._path_opener = path_opener or open_local_path
        self._profiles = store.load()
        self._selected_id = self._profiles[0].id if self._profiles else ""

    @Property(list, notify=changed)
    def rows(self) -> list[dict[str, str | bool]]:
        return [self._row(profile) for profile in self._profiles]

    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._profiles)

    @Property(bool, notify=changed)
    def isEmpty(self) -> bool:
        return not self._profiles

    @Property(str, notify=changed)
    def selectedId(self) -> str:
        return self._selected_id

    @Property(dict, notify=changed)
    def selected(self) -> dict[str, str | bool]:
        profile = self.profile(self._selected_id)
        return self._row(profile) if profile is not None else {}

    @Property(str, constant=True)
    def libraryPath(self) -> str:
        return str(self._store.path)

    @Property(str, constant=True)
    def keyFolder(self) -> str:
        return str(self._signing_root)

    def profile(self, profile_id_value: str) -> GameProfile | None:
        return next(
            (profile for profile in self._profiles if profile.id == profile_id_value),
            None,
        )

    def profiles_for_source(self, original_package: str) -> tuple[GameProfile, ...]:
        return tuple(
            profile
            for profile in self._profiles
            if profile.original_package == original_package
        )

    def profile_for_target(self, target_package: str) -> GameProfile | None:
        matches = tuple(
            profile for profile in self._profiles if profile.target_package == target_package
        )
        return matches[0] if len(matches) == 1 else None

    def unique_profile_for_source(self, original_package: str) -> GameProfile | None:
        profiles = self.profiles_for_source(original_package)
        return profiles[0] if len(profiles) == 1 else None

    @Slot(str)
    def select(self, profile_id_value: str) -> None:
        if self.profile(profile_id_value) is None or profile_id_value == self._selected_id:
            return
        self._selected_id = profile_id_value
        self.changed.emit()

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

    def record_build(
        self,
        source: BundleDraft,
        target_package: str,
        result: BuildResult,
        patches: tuple[str, ...],
    ) -> GameProfile:
        identity = profile_id(source.package_name, target_package)
        current = self.profile(identity)
        values: dict[str, Any] = {
            "game_name": source.game_name or target_package,
            "source_path": str(source.root),
            "output_path": str(result.output_root),
            "source_version": source.version_code,
            "source_signer_id": (
                source.signer_identity.id if source.signer_identity is not None else ""
            ),
            "patches": patches,
        }
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
    ) -> GameProfile:
        current = next(
            (
                profile
                for profile in self._profiles
                if profile.target_package == result.package_name
            ),
            None,
        )
        original = original_package or (
            current.original_package if current is not None else result.package_name
        )
        obbs = tuple(LibraryObb(item.source.name, item.size) for item in result.obbs)
        values: dict[str, Any] = {
            "game_name": bundle.game_name or result.package_name,
            "output_path": str(bundle.root),
            "installed_version": bundle.version_code,
            "obbs": obbs,
            "last_device_serial": serial,
        }
        if current is None:
            profile = GameProfile.create(
                original_package=original,
                target_package=result.package_name,
                source_version=bundle.version_code,
                **values,
            )
        else:
            profile = current.updated(**values)
        self._replace(profile)
        return profile

    def _replace(self, profile: GameProfile) -> None:
        self._profiles = self._store.upsert(profile)
        self._selected_id = profile.id
        self.changed.emit()

    @staticmethod
    def _row(profile: GameProfile) -> dict[str, str | bool]:
        key_status = "Key ready" if profile.key_available else "Key missing or changed"
        if not profile.signing_keystore and not profile.signing_metadata:
            key_status = "Unsigned build"
        version = profile.installed_version or profile.source_version
        return {
            "id": profile.id,
            "gameName": profile.game_name,
            "originalPackage": profile.original_package,
            "targetPackage": profile.target_package,
            "identity": f"{profile.original_package}  →  {profile.target_package}",
            "version": version,
            "versionText": f"Version {version}" if version else "Version not reported",
            "sourcePath": profile.source_path,
            "outputPath": profile.output_path,
            "keyStatus": key_status,
            "keyReady": profile.key_available,
            "keyPath": profile.signing_keystore,
            "metadataPath": profile.signing_metadata,
            "keySha256": profile.signing_key_sha256,
            "installed": bool(profile.installed_version),
            "status": "Installed" if profile.installed_version else "Built",
            "selected": False,
        }
