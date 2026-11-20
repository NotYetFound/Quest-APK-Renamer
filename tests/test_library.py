import tempfile
import threading
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl

from quest_renamer.domain.analysis import ApkAnalysis
from quest_renamer.domain.build import BuildResult, PackageRewriteReport
from quest_renamer.domain.installation import BundleInstallResult, InstalledObb
from quest_renamer.domain.library import GameProfile, LibraryObb, QuestIdentityRecord
from quest_renamer.domain.models import BundleDraft, DeviceSnapshot, InstalledQuestApp
from quest_renamer.infrastructure.app_paths import AppPaths
from quest_renamer.infrastructure.library_store import GameLibraryStore
from quest_renamer.presentation.app_controller import AppController
from quest_renamer.presentation.library_controller import LibraryController
from quest_renamer.services.preflight import AutomaticPreflight


class UpdateAnalyzer:
    def analyze(self, apk: Path, **kwargs: object) -> ApkAnalysis:
        return ApkAnalysis(apk.resolve(), "com.example.game", version_code="47")


class DifferentGameAnalyzer:
    def analyze(self, apk: Path, **kwargs: object) -> ApkAnalysis:
        return ApkAnalysis(apk.resolve(), "com.other.game", version_code="47")


class RecordingQuestIdentityStore:
    def __init__(self, cache_root: Path | None = None) -> None:
        self.cache_root = cache_root or Path(tempfile.gettempdir()) / "qapkr-test-cache"
        self.records: tuple[QuestIdentityRecord, ...] = ()
        self.saved: list[tuple[str, GameProfile]] = []
        self.deleted: list[tuple[str, str]] = []

    def load(
        self, serial: str, installed_packages: set[str]
    ) -> tuple[QuestIdentityRecord, ...]:
        del serial
        return tuple(
            record for record in self.records if record.package_name in installed_packages
        )

    def save(self, serial: str, profile: GameProfile) -> None:
        self.saved.append((serial, profile))

    def delete(self, serial: str, package_name: str) -> None:
        self.deleted.append((serial, package_name))


class LibraryTests(unittest.TestCase):
    def test_search_matches_names_and_ids_without_hiding_installed_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = LibraryController(
                GameLibraryStore(root / "library.json"),
                signing_root=root / "signing",
                installed_apps=lambda _: (
                    InstalledQuestApp("com.qa.studio.golf", "1", app_name="Mini Golf"),
                    InstalledQuestApp("com.studio.chess", "2", app_name="Chess"),
                ),
            )
            library.setDevice(DeviceSnapshot(True, "connected", "QUEST"))
            self._wait_for_library(library)
            library.setSearchQuery("GOLF")
            self.assertEqual([row["id"] for row in library.rows], ["com.qa.studio.golf"])
            library.selectOffset(1)
            self.assertEqual(library.selectedId, "com.qa.studio.golf")
            library.setSearchQuery("com.studio.chess")
            self.assertEqual(library.selectedId, "")
            self.assertEqual([row["gameName"] for row in library.rows], ["Chess"])
            library.setSearchQuery("not installed")
            self.assertEqual(library.rows, [])
            self.assertEqual(library.count, 2)
            library.setSearchQuery(" ")
            self.assertEqual(len(library.rows), 2)

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    @staticmethod
    def _wait_for_analysis(controller: AppController) -> None:
        deadline = 100
        while controller.isAnalyzing and deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
            deadline -= 1
        QCoreApplication.processEvents()

    @staticmethod
    def _wait_for_library(controller: LibraryController) -> None:
        deadline = 100
        while controller.isLoading and deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
            deadline -= 1
        QCoreApplication.processEvents()

    @staticmethod
    def _wait_for_archive(controller: LibraryController) -> None:
        deadline = 200
        while controller.archiveBusy and deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
            deadline -= 1
        QCoreApplication.processEvents()

    def test_store_round_trips_profiles_and_ignores_invalid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "library.json"
            store = GameLibraryStore(path)
            profile = GameProfile.create(
                game_name="Example",
                original_package="com.example.game",
                target_package="com.dev.example.game",
                obbs=(LibraryObb("main.42.com.dev.example.game.obb", 100),),
            )

            store.save((profile,))

            self.assertEqual(store.load(), (profile,))
            self.assertIn('"format": 1', path.read_text(encoding="utf-8"))

    def test_corrupt_library_is_preserved_and_restored_from_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "library.json"
            store = GameLibraryStore(path)
            profile = GameProfile.create(
                game_name="Example",
                original_package="com.example.game",
                target_package="com.dev.example.game",
            )
            store.save((profile,))
            path.write_text('{"format": 1, "games": [', encoding="utf-8")

            loaded = store.load()

            self.assertEqual(loaded, (profile,))
            self.assertIn("last good backup", store.warning)
            assert store.recovery_path is not None
            self.assertEqual(
                store.recovery_path.read_text(encoding="utf-8"),
                '{"format": 1, "games": [',
            )

    def test_structurally_invalid_library_rows_are_not_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "library.json"
            path.write_text(
                '{"format": 1, "games": [{"id": "incomplete"}]}',
                encoding="utf-8",
            )
            store = GameLibraryStore(path)

            self.assertEqual(store.load(), ())

            self.assertFalse(path.exists())
            self.assertIsNotNone(store.recovery_path)
            self.assertIn("preserved", store.warning)

    def test_build_and_install_are_recorded_without_manual_library_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            output = root / "output"
            signing = root / "signing"
            source_root.mkdir()
            output.mkdir()
            signing.mkdir()
            source_apk = source_root / "game.apk"
            output_apk = output / "com.dev.example.game.apk"
            manifest = output / "release.manifest"
            report = output / "RENAME-REPORT.json"
            keystore = signing / "quest-renamer.p12"
            metadata = signing / "identity.json"
            icon = signing / "visible-name.png"
            source_apk.write_bytes(b"source")
            output_apk.write_bytes(b"signed")
            manifest.touch()
            report.touch()
            keystore.write_bytes(b"key")
            metadata.write_text('{"alias":"q","password":"p"}', encoding="utf-8")
            icon.write_bytes(b"\x89PNG\r\n\x1a\n")
            store = GameLibraryStore(root / "library.json")
            identities = RecordingQuestIdentityStore()
            controller = LibraryController(
                store,
                signing_root=signing,
                device_identities=identities,  # type: ignore[arg-type]
                path_opener=lambda _path: True,
            )
            source = BundleDraft(
                source_root,
                source_apk,
                game_name="Example",
                package_name="com.example.game",
                version_code="47",
            )
            result = BuildResult(
                output,
                output_apk,
                (),
                manifest,
                report,
                PackageRewriteReport(1, 1),
                signing_keystore=keystore,
                signing_metadata=metadata,
                app_label="Quest Visible Example",
                app_icon=icon,
            )

            profile = controller.record_build(
                source,
                "com.dev.example.game",
                result,
                (),
            )
            installed = BundleInstallResult(
                "com.dev.example.game",
                output_apk,
                (
                    InstalledObb(
                        output / "main.47.com.dev.example.game.obb",
                        "/sdcard/Android/obb/com.dev.example.game/"
                        "main.47.com.dev.example.game.obb",
                        123,
                    ),
                ),
                True,
            )
            installed.obbs[0].source.touch()
            controller.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            profile = controller.record_install(
                BundleDraft(
                    output,
                    output_apk,
                    (installed.obbs[0].source,),
                    game_name="Example",
                    package_name="com.dev.example.game",
                    version_code="47",
                ),
                installed,
                "QUEST123",
                original_package="com.example.game",
            )
            self._wait_for_archive(controller)

            self.assertEqual(controller.count, 1)
            self.assertEqual(identities.saved[0][0], "QUEST123")
            self.assertEqual(store.load(), ())
            self.assertEqual(profile.installed_version, "47")
            self.assertEqual(profile.obbs[0].name, "main.47.com.dev.example.game.obb")
            self.assertEqual(profile.game_name, "Quest Visible Example")
            self.assertEqual(profile.app_icon, str(icon))
            self.assertEqual(controller.rows[0]["status"], "Managed")
            self.assertTrue(controller.rows[0]["keyReady"])
            self.assertTrue(controller.rows[0]["storedOnQuest"])

            controller.deleteSelected()
            self._wait_for_archive(controller)
            self.assertEqual(
                identities.deleted,
                [("QUEST123", "com.dev.example.game")],
            )
            self.assertFalse(controller.rows[0]["managed"])

    def test_connected_library_shows_installed_apps_with_saved_identity_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signing = root / "signing"
            signing.mkdir()
            key = signing / "key.p12"
            metadata = signing / "key.json"
            icon = signing / "example.png"
            key.write_bytes(b"key")
            metadata.write_text('{"alias":"q","password":"p"}', encoding="utf-8")
            icon.write_bytes(b"\x89PNG\r\n\x1a\n")
            store = GameLibraryStore(root / "library.json")
            store.save(
                (
                    GameProfile.create(
                        game_name="Renamed Example",
                        original_package="com.example.original",
                        target_package="com.dev.example.original",
                        app_icon=str(icon),
                        signing_keystore=str(key),
                        signing_metadata=str(metadata),
                    ),
                )
            )

            library = LibraryController(
                store,
                signing_root=signing,
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.other.game", "9", "1.1"),
                    InstalledQuestApp("com.example.original", "46", "1.9"),
                    InstalledQuestApp("com.dev.example.original", "47", "2.0"),
                ),
            )

            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)

            self.assertTrue(library.showInstalled)
            self.assertEqual(library.count, 3)
            managed = next(row for row in library.rows if row["managed"])
            original = next(
                row for row in library.rows if row["id"] == "com.example.original"
            )
            direct = next(row for row in library.rows if row["id"] == "com.other.game")
            self.assertEqual(managed["gameName"], "Renamed Example")
            self.assertEqual(managed["status"], "Managed")
            self.assertTrue(managed["keyReady"])
            self.assertEqual(original["gameName"], "Renamed Example")
            self.assertEqual(original["iconUrl"], managed["iconUrl"])
            self.assertFalse(original["managed"])
            self.assertEqual(direct["status"], "Direct update")
            self.assertEqual(direct["versionText"], "1.1  (code 9)")

    def test_finished_folder_install_after_restart_keeps_its_pending_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            output = root / "output"
            signing = root / "signing"
            source_root.mkdir()
            output.mkdir()
            signing.mkdir()
            source_apk = source_root / "game.apk"
            output_apk = output / "com.dev.example.game.apk"
            key = signing / "key.p12"
            metadata = signing / "identity.json"
            source_apk.write_bytes(b"source")
            output_apk.write_bytes(b"signed")
            key.write_bytes(b"key")
            metadata.write_text('{"alias":"q","password":"p"}', encoding="utf-8")
            manifest = output / "release.manifest"
            report = output / "RENAME-REPORT.json"
            manifest.touch()
            report.write_text(
                '{"packages":{"source":"com.example.game",'
                '"output":"com.dev.example.game"}}',
                encoding="utf-8",
            )
            store = GameLibraryStore(root / "library.json")
            before_restart = LibraryController(store, signing_root=signing)
            before_restart.record_build(
                BundleDraft(
                    source_root,
                    source_apk,
                    game_name="Example",
                    package_name="com.example.game",
                    version_code="47",
                ),
                "com.dev.example.game",
                BuildResult(
                    output,
                    output_apk,
                    (),
                    manifest,
                    report,
                    PackageRewriteReport(1, 1),
                    signing_keystore=key,
                    signing_metadata=metadata,
                ),
                (),
            )

            identities = RecordingQuestIdentityStore()
            after_restart = LibraryController(
                store,
                signing_root=signing,
                device_identities=identities,  # type: ignore[arg-type]
            )
            after_restart.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            profile = after_restart.record_install(
                BundleDraft(
                    output,
                    output_apk,
                    manifest=manifest,
                    game_name="Example",
                    package_name="com.dev.example.game",
                    version_code="47",
                ),
                BundleInstallResult("com.dev.example.game", output_apk, (), True),
                "QUEST123",
            )
            self._wait_for_archive(after_restart)

            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile.original_package, "com.example.game")
            self.assertEqual(identities.saved[0][1].signing_keystore, str(key))
            self.assertEqual(store.load(), ())

    def test_direct_install_updates_live_inventory_without_polluting_key_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_root = root / "game"
            bundle_root.mkdir()
            apk = bundle_root / "game.apk"
            apk.write_bytes(b"apk")
            library = LibraryController(
                GameLibraryStore(root / "library.json"),
                signing_root=root / "signing",
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )

            profile = library.record_install(
                BundleDraft(
                    bundle_root,
                    apk,
                    game_name="Example Game",
                    package_name="com.example.game",
                    version_code="9",
                ),
                BundleInstallResult("com.example.game", apk, (), True),
                "QUEST123",
            )

            self.assertIsNone(profile)
            self.assertTrue(library.showInstalled)
            self.assertEqual(library.count, 1)
            self.assertEqual(library.rows[0]["gameName"], "Example Game")
            self.assertFalse(library.rows[0]["managed"])
            library.setShowInstalled(False)
            self.assertEqual(library.count, 1)

    def test_library_is_always_the_connected_headset_view(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = LibraryController(
                GameLibraryStore(Path(temporary) / "library.json"),
                signing_root=Path(temporary) / "signing",
                installed_apps=lambda _serial: (),
            )

            snapshot = DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            library.setDevice(snapshot)
            self._wait_for_library(library)
            self.assertTrue(library.showInstalled)

            library.setShowInstalled(False)
            library.setDevice(snapshot)
            self.assertTrue(library.showInstalled)

            library.setDevice(DeviceSnapshot(False, "disconnected"))
            library.setDevice(snapshot)
            self.assertTrue(library.showInstalled)

    def test_migration_identity_information_can_be_copied_for_an_installed_app(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "key.p12"
            metadata = root / "identity.json"
            key.write_bytes(b"private-key")
            metadata.write_text(
                '{"alias":"quest","password":"copy-me"}',
                encoding="utf-8",
            )
            profile = GameProfile.create(
                game_name="Example Game",
                original_package="com.example.game",
                target_package="com.dev.example.game",
                signing_keystore=str(key),
                signing_metadata=str(metadata),
            )
            store = GameLibraryStore(root / "library.json")
            store.save((profile,))
            copied: list[str] = []
            library = LibraryController(
                store,
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "1"),
                ),
                clipboard_writer=lambda value: not copied.append(value),
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)

            library.copySelectedInformation()

            self.assertIn("Original package: com.example.game", copied[0])
            self.assertIn('"password": "copy-me"', copied[0])

    def test_vault_exports_and_imports_a_complete_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "key.p12"
            metadata = root / "identity.json"
            key.write_bytes(b"private-key")
            metadata.write_text(
                '{"alias":"quest","password":"secret"}',
                encoding="utf-8",
            )
            profile = GameProfile.create(
                game_name="Example Game",
                original_package="com.example.game",
                target_package="com.dev.example.game",
                signing_keystore=str(key),
                signing_metadata=str(metadata),
            )
            source_store = GameLibraryStore(root / "source-library.json")
            source_store.save((profile,))
            source = LibraryController(
                source_store,
                signing_root=root / "source-signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "1"),
                ),
            )
            source.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(source)
            archive = root / "saved-library.qarlib"

            source.exportAll(QUrl.fromLocalFile(str(archive)))
            self._wait_for_archive(source)

            destination_store = GameLibraryStore(root / "destination-library.json")
            destination_identities = RecordingQuestIdentityStore(root / "identity-cache")
            destination = LibraryController(
                destination_store,
                signing_root=root / "destination-signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "1"),
                ),
                device_identities=destination_identities,  # type: ignore[arg-type]
            )
            destination.setDevice(
                DeviceSnapshot(True, "connected", "QUEST456", "Meta Quest 3S")
            )
            self._wait_for_library(destination)
            prompts: list[str] = []
            destination.importConfirmationRequested.connect(prompts.append)
            destination.prepareImport(QUrl.fromLocalFile(str(archive)))
            self._wait_for_archive(destination)

            self.assertIn("Import 1 saved identity", prompts[0])
            destination.confirmImport()
            self._wait_for_archive(destination)

            self.assertTrue(destination.showInstalled)
            self.assertEqual(destination.count, 1)
            imported = destination.profile(profile.id)
            self.assertIsNotNone(imported)
            assert imported is not None
            self.assertTrue(imported.key_available)
            self.assertNotEqual(imported.signing_keystore, profile.signing_keystore)
            self.assertEqual(destination_identities.saved[0][0], "QUEST456")

    def test_saved_identities_with_equal_display_names_share_an_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            icon = root / "example.png"
            icon.write_bytes(b"\x89PNG\r\n\x1a\n")
            store = GameLibraryStore(root / "library.json")
            store.save(
                (
                    GameProfile.create(
                        game_name="Example Game",
                        original_package="com.example.game",
                        target_package="com.dev.example.game",
                        app_icon=str(icon),
                    ),
                    GameProfile.create(
                        game_name=" example  GAME ",
                        original_package="com.example.game",
                        target_package="com.qa.example.game",
                    ),
                )
            )

            library = LibraryController(
                store,
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "1"),
                    InstalledQuestApp("com.qa.example.game", "1"),
                ),
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)

            self.assertEqual(library.rows[0]["iconUrl"], library.rows[1]["iconUrl"])

    def test_library_rows_are_cached_until_key_health_is_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "key.p12"
            metadata = root / "key.json"
            key.write_bytes(b"key")
            metadata.write_text("{}", encoding="utf-8")
            store = GameLibraryStore(root / "library.json")
            store.save(
                (
                    GameProfile.create(
                        game_name="Example",
                        original_package="com.example.game",
                        target_package="com.dev.example.game",
                        signing_keystore=str(key),
                        signing_metadata=str(metadata),
                    ),
                )
            )
            library = LibraryController(
                store,
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "1"),
                ),
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)

            first = library.rows
            self.assertIs(first, library.rows)
            self.assertTrue(first[0]["keyReady"])
            key.unlink()
            self.assertTrue(library.rows[0]["keyReady"])

            library.refreshKeyHealth()

            self.assertFalse(library.rows[0]["keyReady"])

    def test_switching_headsets_during_scan_cannot_wedge_or_apply_stale_apps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_started = threading.Event()
            release_first = threading.Event()

            def installed_apps(serial: str) -> tuple[InstalledQuestApp, ...]:
                if serial == "QUEST-A":
                    first_started.set()
                    release_first.wait(timeout=2)
                    return (InstalledQuestApp("com.first.game", "1"),)
                return (InstalledQuestApp("com.second.game", "2"),)

            library = LibraryController(
                GameLibraryStore(Path(temporary) / "library.json"),
                signing_root=Path(temporary) / "signing",
                installed_apps=installed_apps,
            )
            library.setShowInstalled(True)
            library.setDevice(DeviceSnapshot(True, "connected", "QUEST-A", "Quest A"))
            self.assertTrue(first_started.wait(timeout=1))

            library.setDevice(DeviceSnapshot(True, "connected", "QUEST-B", "Quest B"))
            self._wait_for_library(library)

            self.assertFalse(library.isLoading)
            self.assertEqual([row["id"] for row in library.rows], ["com.second.game"])
            release_first.set()
            for _ in range(10):
                QCoreApplication.processEvents()
                time.sleep(0.005)
            self.assertEqual([row["id"] for row in library.rows], ["com.second.game"])

    def test_dashboard_source_restores_the_saved_id_and_key_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "update"
            signing = root / "signing"
            source.mkdir()
            signing.mkdir()
            apk = source / "game.apk"
            apk.write_bytes(b"apk")
            key = signing / "key.p12"
            metadata = signing / "key.json"
            key.write_bytes(b"key")
            metadata.write_text('{"alias":"q","password":"p"}', encoding="utf-8")
            store = GameLibraryStore(root / "library.json")
            profile = GameProfile.create(
                game_name="Example",
                original_package="com.example.game",
                target_package="com.qa.example.game",
                installed_version="42",
                signing_keystore=str(key),
                signing_metadata=str(metadata),
            )
            store.save((profile,))
            library = LibraryController(
                store,
                signing_root=signing,
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.qa.example.game", "42"),
                ),
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)
            controller = AppController(
                analyzer=UpdateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=object(),  # type: ignore[arg-type]
                library_controller=library,
                paths=AppPaths(root / "data", root / "cache"),
            )

            controller.chooseFolder(QUrl.fromLocalFile(str(source)))
            self._wait_for_analysis(controller)

            self.assertEqual(controller.packageId, "com.qa.example.game")
            controller.setSetting("copy_obbs", False)
            self.assertTrue(controller._build_request().copy_obbs)
            self.assertIn("no OBB files found", controller.libraryUpdateSummary)
            self.assertIn("Saved signing identity", controller.libraryMatch)
            request = controller._build_request()
            self.assertIsNotNone(request)
            self.assertEqual(request.signing_keystore, key)  # type: ignore[union-attr]
            self.assertEqual(request.signing_metadata, metadata)  # type: ignore[union-attr]
            # A newer download can replace the contents without changing the folder name.
            obb_dir = source / "com.example.game"
            obb_dir.mkdir()
            obb = obb_dir / "main.47.com.example.game.obb"
            obb.write_bytes(b"updated expansion")
            controller.chooseFolder(QUrl.fromLocalFile(str(source)))
            self._wait_for_analysis(controller)
            refreshed = controller._build_request()
            self.assertIsNotNone(refreshed)
            self.assertTrue(refreshed.copy_obbs)  # type: ignore[union-attr]
            self.assertEqual(refreshed.source.obbs, (obb.resolve(),))  # type: ignore[union-attr]
            self.assertIn("1 OBB", controller.libraryUpdateSummary)

    def test_saved_key_vault_entry_cannot_start_a_direct_quest_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "update"
            source.mkdir()
            (source / "other.apk").write_bytes(b"apk")
            store = GameLibraryStore(root / "library.json")
            profile = GameProfile.create(
                game_name="Example",
                original_package="com.example.game",
                target_package="com.dev.example.game",
            )
            store.save((profile,))
            library = LibraryController(
                store,
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "42"),
                ),
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)
            controller = AppController(
                analyzer=DifferentGameAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=object(),  # type: ignore[arg-type]
                library_controller=library,
                paths=AppPaths(root / "data", root / "cache"),
            )

            controller.prepareLibraryUpdate(profile.target_package)
            controller.chooseLibraryUpdate(QUrl.fromLocalFile(str(source)))
            self._wait_for_analysis(controller)

            self.assertEqual(controller.packageId, "")
            self.assertEqual(controller.libraryMatch, "")
            self.assertIn("different game", controller.notice)

    def test_missing_saved_key_blocks_an_installed_library_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "update"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            store = GameLibraryStore(root / "library.json")
            profile = GameProfile.create(
                game_name="Example",
                original_package="com.example.game",
                target_package="com.dev.example.game",
                installed_version="42",
                signing_keystore=str(root / "missing.p12"),
                signing_metadata=str(root / "missing.json"),
            )
            store.save((profile,))
            library = LibraryController(
                store,
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "42"),
                ),
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)
            controller = AppController(
                analyzer=UpdateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=object(),  # type: ignore[arg-type]
                library_controller=library,
                paths=AppPaths(root / "data", root / "cache"),
            )

            controller.chooseFolder(QUrl.fromLocalFile(str(source)))
            self._wait_for_analysis(controller)

            self.assertFalse(controller.canBuild)
            self.assertIn("signing key", controller.notice)

    def test_corrupt_headset_identity_blocks_update_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identities = RecordingQuestIdentityStore(root / "identity-cache")
            identities.records = (
                QuestIdentityRecord(
                    "com.dev.example.game",
                    error="QAPKR signing identity failed its checksum check.",
                ),
            )
            library = LibraryController(
                GameLibraryStore(root / "library.json"),
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.dev.example.game", "42"),
                ),
                device_identities=identities,  # type: ignore[arg-type]
            )
            library.setDevice(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)
            controller = AppController(
                analyzer=UpdateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=object(),  # type: ignore[arg-type]
                library_controller=library,
                paths=AppPaths(root / "data", root / "cache"),
            )

            controller.prepareLibraryUpdate("com.dev.example.game")

            self.assertIn("needs attention", controller.notice)
            self.assertEqual(library.rows[0]["status"], "Key issue")

    def test_plain_installed_app_update_is_kept_unmodified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "update"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            library = LibraryController(
                GameLibraryStore(root / "library.json"),
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    InstalledQuestApp("com.example.game", "42", "1.0"),
                ),
            )
            controller = AppController(
                analyzer=UpdateAnalyzer(),
                bundle_installer=object(),  # type: ignore[arg-type]
                library_controller=library,
                paths=AppPaths(root / "data", root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Meta Quest 3")
            )
            self._wait_for_library(library)

            controller.prepareLibraryUpdate("com.example.game")
            controller.chooseLibraryUpdate(QUrl.fromLocalFile(str(source)))
            self._wait_for_analysis(controller)

            self.assertTrue(controller.isDirectLibraryUpdate)
            self.assertEqual(controller.packageId, "com.example.game")
            self.assertEqual(controller.buildActionLabel, "Install update")
            self.assertTrue(controller.canBuild)

            controller.startOver()

            self.assertFalse(controller.isDirectLibraryUpdate)
            self.assertEqual(controller.libraryMatch, "")
            self.assertEqual(controller.buildActionLabel, "Build renamed copy")


if __name__ == "__main__":
    unittest.main()
