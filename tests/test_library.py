import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl

from quest_renamer.domain.analysis import ApkAnalysis
from quest_renamer.domain.build import BuildResult, PackageRewriteReport
from quest_renamer.domain.installation import BundleInstallResult, InstalledObb
from quest_renamer.domain.library import GameProfile, LibraryObb
from quest_renamer.domain.models import BundleDraft
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


class LibraryTests(unittest.TestCase):
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
            source_apk.write_bytes(b"source")
            output_apk.write_bytes(b"signed")
            manifest.touch()
            report.touch()
            keystore.write_bytes(b"key")
            metadata.write_text('{"alias":"q","password":"p"}', encoding="utf-8")
            store = GameLibraryStore(root / "library.json")
            controller = LibraryController(
                store,
                signing_root=signing,
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

            self.assertEqual(controller.count, 1)
            self.assertEqual(profile.installed_version, "47")
            self.assertEqual(profile.obbs[0].name, "main.47.com.dev.example.game.obb")
            self.assertEqual(controller.rows[0]["status"], "Installed")
            self.assertTrue(controller.rows[0]["keyReady"])

    def test_selecting_a_library_update_restores_the_saved_id_and_key(self) -> None:
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
            library = LibraryController(store, signing_root=signing)
            controller = AppController(
                analyzer=UpdateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=object(),  # type: ignore[arg-type]
                library_controller=library,
                paths=AppPaths(root / "data", root / "cache"),
            )

            controller.prepareLibraryUpdate(profile.id)
            controller.chooseLibraryUpdate(QUrl.fromLocalFile(str(source)))
            self._wait_for_analysis(controller)

            self.assertEqual(controller.packageId, "com.qa.example.game")
            self.assertIn("42 → 47", controller.libraryMatch)
            request = controller._build_request()
            self.assertIsNotNone(request)
            self.assertEqual(request.signing_keystore, key)  # type: ignore[union-attr]
            self.assertEqual(request.signing_metadata, metadata)  # type: ignore[union-attr]

    def test_selected_update_must_match_the_library_game(self) -> None:
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
            library = LibraryController(store, signing_root=root / "signing")
            controller = AppController(
                analyzer=DifferentGameAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=object(),  # type: ignore[arg-type]
                library_controller=library,
                paths=AppPaths(root / "data", root / "cache"),
            )

            controller.prepareLibraryUpdate(profile.id)
            controller.chooseLibraryUpdate(QUrl.fromLocalFile(str(source)))
            self._wait_for_analysis(controller)

            self.assertEqual(controller.packageId, "com.dev.other.game")
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
            library = LibraryController(store, signing_root=root / "signing")
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


if __name__ == "__main__":
    unittest.main()
