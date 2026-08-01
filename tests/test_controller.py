import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl

from quest_renamer.domain.analysis import ApkAnalysis
from quest_renamer.domain.build import BuildResult, PackageRewriteReport
from quest_renamer.domain.installation import (
    BundleInstallError,
    BundleInstallResult,
    InstalledObb,
    InstalledPackageConflict,
)
from quest_renamer.domain.models import BundleDraft, DeviceSnapshot
from quest_renamer.domain.signers import SignerIdentity
from quest_renamer.infrastructure.app_paths import AppPaths
from quest_renamer.infrastructure.build_recovery import write_build_recovery
from quest_renamer.infrastructure.settings_store import JsonSettingsStore
from quest_renamer.infrastructure.signing_backup import SigningIdentityManager
from quest_renamer.main import (
    configure_packaged_rendering,
    initial_folder,
    older_firmware_patch_candidates,
    package_resource_root,
)
from quest_renamer.presentation.app_controller import AppController
from quest_renamer.services.preflight import AutomaticPreflight


class ImmediateAnalyzer:
    def analyze(self, apk: Path, **kwargs: object) -> ApkAnalysis:
        progress = kwargs.get("progress")
        if callable(progress):
            progress(1.0, "APK checked")
        return ApkAnalysis(apk.resolve(), "com.example.game", version_code="42")


class LineageAnalyzer:
    def analyze(self, apk: Path, **kwargs: object) -> ApkAnalysis:
        return ApkAnalysis(
            apk.resolve(),
            "com.example.game",
            signer_identity=SignerIdentity("nif", "NIF", "NothingIsFree"),
            signer_lineage="Previously signed by Meta (META)",
            has_legacy_loader=True,
        )


class ImmediateBuilder:
    def build(self, request: object, **kwargs: object) -> BuildResult:
        output = request.output_root  # type: ignore[union-attr]
        output.mkdir()
        apk = output / "com.dev.example.game.apk"
        manifest = output / "release.manifest"
        report = output / "quest-renamer-report.json"
        apk.write_bytes(b"signed")
        manifest.touch()
        report.touch()
        return BuildResult(
            output,
            apk,
            (),
            manifest,
            report,
            PackageRewriteReport(1, 1),
        )


class ImmediateBundleInstaller:
    def __init__(self) -> None:
        self.installed: BundleDraft | None = None

    def install_bundle(
        self, bundle: BundleDraft, serial: str, **kwargs: object
    ) -> BundleInstallResult:
        self.installed = bundle
        progress = kwargs.get("progress")
        if callable(progress):
            progress(1.0, "Install verified")
        return BundleInstallResult(
            bundle.package_name,
            bundle.apk,
            tuple(
                InstalledObb(
                    obb,
                    f"/sdcard/Android/obb/{bundle.package_name}/{obb.name}",
                    obb.stat().st_size,
                )
                for obb in bundle.obbs
            ),
            True,
        )

    def retry_obbs(
        self, bundle: BundleDraft, serial: str, **kwargs: object
    ) -> BundleInstallResult:
        return self.install_bundle(bundle, serial, **kwargs)


class RetryBundleInstaller(ImmediateBundleInstaller):
    def __init__(self) -> None:
        super().__init__()
        self.retry_count = 0

    def install_bundle(
        self, bundle: BundleDraft, serial: str, **kwargs: object
    ) -> BundleInstallResult:
        self.installed = bundle
        raise BundleInstallError(
            "Quest reported the wrong size for the OBB.",
            failed_obbs=bundle.obbs,
        )

    def retry_obbs(
        self, bundle: BundleDraft, serial: str, **kwargs: object
    ) -> BundleInstallResult:
        self.retry_count += 1
        return super().install_bundle(bundle, serial, **kwargs)


class ConflictBundleInstaller(ImmediateBundleInstaller):
    def __init__(self) -> None:
        super().__init__()
        self.confirmed = False

    def install_bundle(
        self,
        bundle: BundleDraft,
        serial: str,
        *,
        allow_existing: bool = False,
        **kwargs: object,
    ) -> BundleInstallResult:
        if not allow_existing:
            raise InstalledPackageConflict(bundle.package_name)
        self.confirmed = True
        return super().install_bundle(bundle, serial, **kwargs)


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_package_resources_resolve_inside_a_frozen_bundle(self) -> None:
        frozen = Path("/app/_internal")
        self.assertEqual(
            package_resource_root(frozen_root=frozen),
            frozen / "quest_renamer",
        )

    def test_packaged_firmware_loader_is_a_supported_candidate(self) -> None:
        package_root = Path("/app/_internal/quest_renamer")
        data_root = Path("/home/test/.local/share/quest-renamer")

        candidates = older_firmware_patch_candidates(package_root, data_root)

        self.assertEqual(
            candidates[0], package_root / "tools" / "libovrplatformloader.so"
        )

    def test_packaged_linux_uses_software_rendering(self) -> None:
        environment: dict[str, str] = {}

        configure_packaged_rendering(
            platform_name="linux",
            frozen=True,
            environment=environment,
        )

        self.assertEqual(environment["QT_QUICK_BACKEND"], "software")

    def test_packaged_rendering_preserves_an_explicit_override(self) -> None:
        environment = {"QT_QUICK_BACKEND": "rhi"}

        configure_packaged_rendering(
            platform_name="linux",
            frozen=True,
            environment=environment,
        )

        self.assertEqual(environment["QT_QUICK_BACKEND"], "rhi")

    def test_source_windows_and_macos_runs_keep_the_native_renderer(self) -> None:
        source_environment: dict[str, str] = {}
        windows_environment: dict[str, str] = {}
        macos_environment: dict[str, str] = {}

        configure_packaged_rendering(
            platform_name="linux",
            frozen=False,
            environment=source_environment,
        )
        configure_packaged_rendering(
            platform_name="win32",
            frozen=True,
            environment=windows_environment,
        )
        configure_packaged_rendering(
            platform_name="darwin",
            frozen=True,
            environment=macos_environment,
        )

        self.assertNotIn("QT_QUICK_BACKEND", source_environment)
        self.assertNotIn("QT_QUICK_BACKEND", windows_environment)
        self.assertNotIn("QT_QUICK_BACKEND", macos_environment)

    def test_startup_recovers_an_interrupted_staging_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = AppPaths(root / "data", root / "cache")
            staging = root / ".finished.staging-interrupted"
            staging.mkdir()
            write_build_recovery(
                paths.build_recovery_file,
                staging=staging,
                source=root / "source",
                output=root / "finished",
            )

            controller = AppController(paths=paths)

            self.assertEqual(controller.partialOutputFolder, str(staging.resolve()))
            controller.keepPartialBuild()
            self.assertFalse(paths.build_recovery_file.exists())
            self.assertTrue(staging.is_dir())

    def test_support_text_has_environment_tools_and_only_displays_latest_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = AppPaths(root / "data", root / "cache")
            paths.log_file.parent.mkdir(parents=True)
            paths.log_file.write_text(
                "[2026-08-01T10:00:00+00:00] [APP] Session started\n"
                "    Version: old\n"
                "[2026-08-01T10:00:01+00:00] [INFO] Old session detail\n",
                encoding="utf-8",
            )

            controller = AppController(
                paths=paths,
                support_tool_summary="Apktool test (ready)",
            )

            self.assertIn(
                "Earlier sessions remain in the saved log.", controller.activityDisplayText
            )
            self.assertNotIn("Old session detail", controller.activityDisplayText)
            self.assertIn(
                "QUEST APK RENAMER — SUPPORT INFORMATION", controller.supportInformation
            )
            self.assertIn("Apktool test (ready)", controller.supportInformation)
            self.assertIn("Old session detail", controller.supportInformation)

    def test_folder_argument_accepts_an_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            self.assertEqual(
                initial_folder(["--style", "Basic", str(folder)]), folder.resolve()
            )

    def test_controller_is_ready_after_a_bundle_is_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "game.apk").write_bytes(b"apk")
            (folder / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Example;Example;com.studio.game;42\n",
                encoding="utf-8",
            )
            controller = AppController(
                paths=AppPaths(data=folder / "data", cache=folder / "cache"),
                build_engine=object(),  # type: ignore[arg-type]
            )

            controller.chooseFolder(QUrl.fromLocalFile(str(folder)))

            self.assertTrue(controller.hasBundle)
            self.assertEqual(controller.packageId, "com.dev.studio.game")
            self.assertTrue(controller.canBuild)

    def test_single_apk_selection_is_exact_and_mr_preset_inserts_a_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            selected = folder / "selected.apk"
            selected.write_bytes(b"selected")
            (folder / "other.apk").write_bytes(b"other")
            (folder / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Example;Example;com.studio.game;42\n",
                encoding="utf-8",
            )
            controller = AppController(
                paths=AppPaths(data=folder / "data", cache=folder / "cache"),
                build_engine=object(),  # type: ignore[arg-type]
            )

            controller.chooseFolder(QUrl.fromLocalFile(str(selected)))
            controller.applyTag("mr")

            self.assertTrue(controller.hasBundle)
            self.assertEqual(controller.apkName, "selected.apk")
            self.assertEqual(controller.packageId, "com.mr.studio.game")

    def test_setting_change_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = AppPaths(data=root / "data", cache=root / "cache")
            store = JsonSettingsStore(paths.settings_file)
            controller = AppController(paths=paths, settings_store=store)

            controller.setSetting("copy_obbs", False)

            self.assertFalse(store.load().copy_obbs)
            self.assertFalse(controller.settings["copyObbs"])

    def test_output_parent_changes_the_computed_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "exports"
            source.mkdir()
            destination.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            (source / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Example;Example;com.example.game;42\n",
                encoding="utf-8",
            )
            controller = AppController(
                build_engine=object(),  # type: ignore[arg-type]
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )

            controller.chooseFolderPath(str(source))
            controller.chooseOutputParent(QUrl.fromLocalFile(str(destination)))

            self.assertEqual(
                controller.outputFolder,
                str(destination.resolve() / "source - Renamed"),
            )

    def test_dashboard_reports_signer_lineage_and_allows_patch_only_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            controller = AppController(
                analyzer=LineageAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=object(),  # type: ignore[arg-type]
                older_firmware_asset_available=True,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )

            controller.chooseFolderPath(str(source))
            self._wait_until(lambda: controller.sourcePackage == "com.example.game")
            controller.setSetting("older_firmware_patch", True)
            controller.setPackageId("com.example.game")

            self.assertTrue(controller.canBuild)
            self.assertEqual(controller.buildActionLabel, "Apply firmware patch")
            self.assertIn("NothingIsFree", controller.signerLineage)
            self.assertIn("Previously signed by Meta", controller.signerLineage)

    def test_finished_build_uses_cross_desktop_path_opener(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            opened: list[Path] = []
            controller = AppController(
                analyzer=ImmediateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=ImmediateBuilder(),
                path_opener=lambda path: not opened.append(path),
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )

            controller.chooseFolderPath(str(source))
            self._wait_until(lambda: controller.canBuild)
            controller.requestBuild()
            self._wait_until(lambda: controller.buildActionLabel == "Open finished folder")
            controller.requestBuild()

            self.assertEqual(opened, [Path(controller.outputFolder)])

    def test_analysis_and_build_complete_without_blocking_the_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            controller = AppController(
                analyzer=ImmediateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=ImmediateBuilder(),
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )

            controller.chooseFolder(QUrl.fromLocalFile(str(source)))
            self._wait_until(lambda: controller.canBuild)
            controller.requestBuild()
            self._wait_until(lambda: controller.buildActionLabel == "Open finished folder")

            self.assertEqual(controller.sourcePackage, "com.example.game")
            self.assertEqual(controller.packageId, "com.dev.example.game")
            self.assertIn("built, signed", controller.notice)

    def test_selected_finished_folder_installs_apk_and_obbs_as_one_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finished = root / "finished"
            obb_folder = finished / "com.example.game"
            obb_folder.mkdir(parents=True)
            (finished / "game.apk").write_bytes(b"apk")
            (obb_folder / "main.42.com.example.game.obb").write_bytes(b"obb")
            (finished / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Example;Example;com.example.game;42\n",
                encoding="utf-8",
            )
            installer = ImmediateBundleInstaller()
            controller = AppController(
                bundle_installer=installer,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1_000_000)
            )

            controller.installFinishedFolder(QUrl.fromLocalFile(str(finished)))
            self._wait_until(lambda: "Install verified" in controller.notice)

            self.assertIsNotNone(installer.installed)
            assert installer.installed is not None
            self.assertEqual(installer.installed.package_name, "com.example.game")
            self.assertEqual(len(installer.installed.obbs), 1)

    def test_finished_folder_install_is_disabled_until_a_quest_is_connected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = AppController(
                bundle_installer=ImmediateBundleInstaller(),
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )

            self.assertFalse(controller.canInstallFolder)

            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1_000_000)
            )

            self.assertTrue(controller.canInstallFolder)

    def test_cleanup_removes_only_the_folder_that_was_verified_and_installed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            installer = ImmediateBundleInstaller()
            controller = AppController(
                analyzer=ImmediateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=ImmediateBuilder(),
                bundle_installer=installer,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1_000_000)
            )
            controller.setSetting("delete_source_after_install", True)
            controller.chooseFolder(QUrl.fromLocalFile(str(source)))
            self._wait_until(lambda: controller.canBuild)
            controller.requestBuild()
            self._wait_until(lambda: controller.canInstallBuilt)
            finished = Path(controller.outputFolder)

            controller.installBuiltFolder()
            self._wait_until(lambda: not finished.exists())

            self.assertTrue(source.exists())
            self.assertFalse(finished.exists())
            self._wait_until(lambda: "Cleaned up installed folder" in controller.activityText)
            self.assertIn("deleted", controller.notice)

    def test_replace_source_and_install_cleanup_can_both_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            paths = AppPaths(data=root / "data", cache=root / "cache")
            store = JsonSettingsStore(paths.settings_file)
            controller = AppController(paths=paths, settings_store=store)
            confirmations: list[bool] = []
            controller.replaceSourceConfirmationRequested.connect(
                lambda: confirmations.append(True)
            )
            controller.setSetting("copy_obbs", False)
            controller.setSetting("delete_source_after_install", True)
            controller.chooseFolderPath(str(source))

            controller.requestReplaceSource(True)

            self.assertEqual(confirmations, [True])
            self.assertFalse(controller.settings["replaceSourceAfterBuild"])
            controller.confirmReplaceSource()

            saved = store.load()
            self.assertTrue(saved.replace_source_after_build)
            self.assertTrue(saved.delete_source_after_install)
            self.assertTrue(saved.copy_obbs)
            self.assertEqual(controller.outputFolder, str(source.resolve()))

    def test_failed_obb_transfer_can_retry_without_starting_a_new_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finished = root / "finished"
            obb_folder = finished / "com.example.game"
            obb_folder.mkdir(parents=True)
            (finished / "game.apk").write_bytes(b"apk")
            (obb_folder / "main.42.com.example.game.obb").write_bytes(b"obb")
            (finished / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Example;Example;com.example.game;42\n",
                encoding="utf-8",
            )
            installer = RetryBundleInstaller()
            controller = AppController(
                bundle_installer=installer,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1_000_000)
            )

            controller.installFinishedFolder(QUrl.fromLocalFile(str(finished)))
            self._wait_until(lambda: controller.canRetryObbs)
            controller.retryFailedObbs()
            self._wait_until(lambda: "Install verified" in controller.notice)

            self.assertEqual(installer.retry_count, 1)
            self.assertFalse(controller.canRetryObbs)

    def test_install_is_blocked_when_the_bundle_will_not_fit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finished = root / "finished"
            finished.mkdir()
            (finished / "game.apk").write_bytes(b"larger than one byte")
            (finished / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Example;Example;com.example.game;42\n",
                encoding="utf-8",
            )
            installer = ImmediateBundleInstaller()
            controller = AppController(
                bundle_installer=installer,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1)
            )

            controller.installFinishedFolder(QUrl.fromLocalFile(str(finished)))

            self.assertIsNone(installer.installed)
            self.assertIn("only has 1 B free", controller.notice)

    def test_existing_package_requires_confirmation_before_install_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finished = root / "finished"
            finished.mkdir()
            (finished / "game.apk").write_bytes(b"apk")
            (finished / "release.manifest").write_text(
                "Game Name;Release Name;Package Name;Version Code\n"
                "Example;Example;com.example.game;42\n",
                encoding="utf-8",
            )
            installer = ConflictBundleInstaller()
            controller = AppController(
                bundle_installer=installer,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1_000_000)
            )
            requested: list[str] = []
            controller.packageConflictRequested.connect(requested.append)

            controller.installFinishedFolder(QUrl.fromLocalFile(str(finished)))
            self._wait_until(lambda: bool(requested))
            self.assertFalse(installer.confirmed)
            controller.continuePackageInstall()
            self._wait_until(
                lambda: installer.confirmed and "Install verified" in controller.notice
            )

            self.assertEqual(requested, ["com.example.game"])
            self.assertIn("Install verified", controller.notice)

    def test_key_backup_reminder_and_restore_flow_are_wired_to_the_controller(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "game.apk").write_bytes(b"apk")
            signing = root / "data" / "signing"
            signing.mkdir(parents=True)
            (signing / "quest-renamer.p12").write_bytes(b"current")
            (signing / "identity.json").write_text(
                json.dumps({"alias": "quest-renamer", "password": "secret"}),
                encoding="utf-8",
            )
            manager = SigningIdentityManager(signing)
            controller = AppController(
                analyzer=ImmediateAnalyzer(),
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=ImmediateBuilder(),
                signing_manager=manager,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            reminders: list[bool] = []
            controller.signingBackupReminderRequested.connect(lambda: reminders.append(True))
            controller.chooseFolder(QUrl.fromLocalFile(str(source)))
            self._wait_until(lambda: controller.canBuild)

            controller.requestBuild()
            self._wait_until(lambda: bool(reminders))
            backup_parent = root / "backups"
            backup_parent.mkdir()
            controller.backupSigningKey(QUrl.fromLocalFile(str(backup_parent)))
            self._wait_until(
                lambda: manager.state().backed_up and controller.canRestoreSigningKey
            )

            backup = next(backup_parent.iterdir())
            confirmations: list[str] = []
            controller.signingRestoreConfirmationRequested.connect(confirmations.append)
            controller.restoreSigningKey(QUrl.fromLocalFile(str(backup)))
            self._wait_until(lambda: bool(confirmations))
            self.assertEqual(confirmations, [str(backup.resolve())])
            controller.confirmSigningKeyRestore()
            self._wait_until(lambda: "Signing identity restored" in controller.notice)

            self.assertIn("Signing identity restored", controller.notice)

    def test_old_output_cleanup_requires_report_then_moves_folder_to_trash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "old-output"
            output.mkdir()
            apk = output / "com.example.game.dev.apk"
            apk.write_bytes(b"apk")
            (output / "quest-renamer-report.json").write_text(
                json.dumps(
                    {
                        "application": {
                            "name": "Quest APK Renamer",
                            "version": "1.4.0",
                        },
                        "packages": {"output": "com.example.game.dev"},
                        "apk": {"name": apk.name},
                    }
                ),
                encoding="utf-8",
            )
            trash = root / "trash"
            trash.mkdir()

            def move_to_trash(path: Path) -> None:
                shutil.move(str(path), trash / path.name)

            controller = AppController(
                paths=AppPaths(data=root / "data", cache=root / "cache"),
                move_to_trash=move_to_trash,
            )
            confirmations: list[tuple[str, str, str]] = []
            controller.outputCleanupConfirmationRequested.connect(
                lambda path, size, package: confirmations.append((path, size, package))
            )

            controller.requestOldOutputCleanup(QUrl.fromLocalFile(str(output)))
            self.assertEqual(confirmations[0][2], "com.example.game.dev")
            controller.confirmOldOutputCleanup()
            self._wait_until(lambda: "moved to Trash" in controller.notice)

            self.assertTrue((trash / "old-output").is_dir())
            self.assertIn("moved to Trash", controller.notice)

    def test_log_export_saves_a_readable_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = AppController(paths=AppPaths(data=root / "data", cache=root / "cache"))
            destination = root / "exported" / "support.log"

            controller.exportLog(QUrl.fromLocalFile(str(destination)))

            text = destination.read_text(encoding="utf-8")
            self.assertIn("[APP] Session started", text)
            self.assertIn("Version:", text)

    def _wait_until(self, condition: object) -> None:
        deadline = time.monotonic() + 2
        while not condition():  # type: ignore[operator]
            self.application.processEvents()
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for an asynchronous controller result.")
            time.sleep(0.005)


if __name__ == "__main__":
    unittest.main()
