"""Controller-level regression tests for busy guards, retries, and notifications."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from test_bulk_controller import SelectiveBuilder
from test_controller import ImmediateAnalyzer, ImmediateBundleInstaller

from quest_renamer.domain.installation import BundleInstallError, BundleInstallResult
from quest_renamer.domain.models import BundleDraft, DeviceSnapshot
from quest_renamer.infrastructure.app_paths import AppPaths
from quest_renamer.infrastructure.library_store import GameLibraryStore
from quest_renamer.infrastructure.local_bundles import LocalBundleInspector
from quest_renamer.infrastructure.settings_store import JsonSettingsStore
from quest_renamer.presentation.app_controller import AppController
from quest_renamer.presentation.bulk_controller import BulkController
from quest_renamer.presentation.library_controller import LibraryController
from quest_renamer.services.preflight import AutomaticPreflight


class PushStageFailureInstaller(ImmediateBundleInstaller):
    """Fails while pushing (APK never installed); the retry must rerun the install."""

    def __init__(self) -> None:
        super().__init__()
        self.install_calls = 0
        self.retry_calls = 0

    def install_bundle(
        self, bundle: BundleDraft, serial: str, **kwargs: object
    ) -> BundleInstallResult:
        self.install_calls += 1
        if self.install_calls == 1:
            raise BundleInstallError(
                "OBB transfer failed for main.obb: cable unplugged",
                failed_obbs=bundle.obbs,
                apk_installed=False,
            )
        return super().install_bundle(bundle, serial, **kwargs)

    def retry_obbs(
        self, bundle: BundleDraft, serial: str, **kwargs: object
    ) -> BundleInstallResult:
        self.retry_calls += 1
        return super().install_bundle(bundle, serial, **kwargs)


class IncompatibleSignerInstaller(ImmediateBundleInstaller):
    """First install is refused by the Quest; after an uninstall it succeeds."""

    def __init__(self) -> None:
        super().__init__()
        self.uninstalled: list[str] = []
        self.install_calls = 0

    def install_bundle(
        self, bundle: BundleDraft, serial: str, **kwargs: object
    ) -> BundleInstallResult:
        self.install_calls += 1
        if not self.uninstalled:
            raise BundleInstallError(
                "The app on the Quest was signed with a different key. "
                "(INSTALL_FAILED_UPDATE_INCOMPATIBLE)"
            )
        return super().install_bundle(bundle, serial, **kwargs)

    def uninstall_package(self, package_name: str, serial: str, **_kwargs: object) -> None:
        self.uninstalled.append(package_name)


class ExplodingInstaller:
    """Raises a non-install exception type, as a runner timeout would."""

    def install_bundle(self, bundle: BundleDraft, serial: str, **kwargs: object) -> None:
        raise RuntimeError("Command exceeded its 1800-second safety deadline.")

    def retry_obbs(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("not used")


class ControllerGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def _wait_until(self, condition: object) -> None:
        deadline = time.monotonic() + 3
        while not condition():  # type: ignore[operator]
            self.application.processEvents()
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for an asynchronous controller result.")
            time.sleep(0.005)

    @staticmethod
    def _finished_folder(root: Path, name: str = "finished") -> Path:
        finished = root / name
        obb_folder = finished / "com.example.game"
        obb_folder.mkdir(parents=True)
        (finished / "game.apk").write_bytes(b"apk")
        (obb_folder / "main.42.com.example.game.obb").write_bytes(b"obb")
        (finished / "release.manifest").write_text(
            "Game Name;Release Name;Package Name;Version Code\n"
            "Example;Example;com.example.game;42\n",
            encoding="utf-8",
        )
        return finished

    def test_choosing_a_source_is_refused_while_work_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._finished_folder(root, "first")
            second = self._finished_folder(root, "second")
            controller = AppController(paths=AppPaths(data=root / "data", cache=root / "cache"))
            controller.chooseFolder(QUrl.fromLocalFile(str(first)))
            self.assertEqual(controller.folderPath, str(first))

            controller._build_state = "running"
            controller.chooseFolder(QUrl.fromLocalFile(str(second)))

            self.assertEqual(controller.folderPath, str(first))
            self.assertIn("Wait for the current operation", controller.notice)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_symlinked_apk_does_not_wedge_the_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real.apk"
            real.write_bytes(b"apk")
            folder = root / "Game"
            folder.mkdir()
            try:
                os.symlink(real, folder / "game.apk")
            except OSError as exc:  # pragma: no cover - restricted environments
                self.skipTest(f"symlinks unavailable: {exc}")
            controller = AppController(
                analyzer=ImmediateAnalyzer(),
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )

            controller.chooseFolder(QUrl.fromLocalFile(str(folder)))
            self._wait_until(lambda: not controller.isAnalyzing)

            self.assertFalse(controller.isBusy)
            self.assertEqual(controller.sourcePackage, "com.example.game")

    def test_device_polls_do_not_overwrite_the_current_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = self._finished_folder(root, "Game")
            controller = AppController(
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=SelectiveBuilder(),
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller.chooseFolder(QUrl.fromLocalFile(str(folder)))
            controller._set_notice("Renamed copy built, signed, and verified.", "success")

            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 5_000_000_000)
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 4_000_000_000)
            )

            self.assertEqual(controller.notice, "Renamed copy built, signed, and verified.")
            self.assertEqual(controller.noticeTone, "success")

    def test_push_stage_failure_retries_with_a_full_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finished = self._finished_folder(root)
            installer = PushStageFailureInstaller()
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

            self.assertEqual(installer.install_calls, 2)
            self.assertEqual(installer.retry_calls, 0)
            self.assertFalse(controller.canRetryObbs)

    def test_signing_conflicts_offer_uninstall_and_reinstall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finished = self._finished_folder(root)
            installer = IncompatibleSignerInstaller()
            controller = AppController(
                bundle_installer=installer,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1_000_000)
            )
            suggestions: list[str] = []
            controller.uninstallSuggested.connect(
                lambda package, _reason: suggestions.append(package)
            )

            controller.installFinishedFolder(QUrl.fromLocalFile(str(finished)))
            self._wait_until(lambda: suggestions)
            controller.confirmUninstallAndReinstall()
            self._wait_until(lambda: "Install verified" in controller.notice)

            self.assertEqual(suggestions, ["com.example.game"])
            self.assertEqual(installer.uninstalled, ["com.example.game"])
            self.assertEqual(installer.install_calls, 2)

    def test_unexpected_installer_exceptions_release_the_busy_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finished = self._finished_folder(root)
            controller = AppController(
                bundle_installer=ExplodingInstaller(),  # type: ignore[arg-type]
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 1_000_000)
            )

            controller.installFinishedFolder(QUrl.fromLocalFile(str(finished)))
            self._wait_until(lambda: not controller.isInstalling)

            self.assertFalse(controller.isBusy)
            self.assertIn("safety deadline", controller.notice)

    def test_recent_folders_are_remembered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = self._finished_folder(root, "Game")
            store = JsonSettingsStore(root / "settings.json")
            controller = AppController(
                settings_store=store,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )

            controller.chooseFolder(QUrl.fromLocalFile(str(folder)))

            self.assertEqual(controller.lastSourceFolder, str(root))
            self.assertEqual(store.load().last_source_folder, str(root))

    def test_copy_text_and_open_helpers_are_safe_without_a_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = AppController(paths=AppPaths(data=root / "data", cache=root / "cache"))
            controller.openSourceFolder()
            controller.openOutputFolder()
            controller.copyText("")
            self.assertFalse(controller.hasBuildResult)
            self.assertEqual(controller.operationElapsed, "")


class BulkGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def _wait_until(self, condition: object) -> None:
        deadline = time.monotonic() + 3
        while not condition():  # type: ignore[operator]
            self.application.processEvents()
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for the bulk controller.")
            time.sleep(0.005)

    @staticmethod
    def _game(folder: Path, package: str) -> None:
        folder.mkdir()
        (folder / "game.apk").write_bytes(b"apk")
        (folder / "release.manifest").write_text(
            "Game Name;Release Name;Package Name;Version Code\n"
            f"{folder.name};{folder.name};{package};42\n",
            encoding="utf-8",
        )

    def test_unexpected_install_exceptions_are_recorded_and_the_queue_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "games"
            parent.mkdir()
            self._game(parent / "First", "com.example.first")
            self._game(parent / "Second", "com.example.second")
            opened: list[Path] = []
            copied: list[str] = []
            controller = BulkController(
                inspector=LocalBundleInspector(),
                analyzer=None,
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=SelectiveBuilder(),
                bundle_installer=ExplodingInstaller(),  # type: ignore[arg-type]
                settings_store=JsonSettingsStore(root / "settings.json"),
                device_snapshot=lambda: DeviceSnapshot(
                    True, "connected", "QUEST123", "Quest 3", 10_000_000_000
                ),
                path_opener=lambda path: opened.append(path) or True,
                clipboard_writer=lambda text: copied.append(text) or True,
            )
            controller.scanParent(QUrl.fromLocalFile(str(parent)))
            self._wait_until(lambda: controller.count == 2)

            controller.requestInstall()
            controller.confirmOperation()
            self._wait_until(lambda: controller.hasOverview)

            self.assertFalse(controller.isBusy)
            self.assertIn("0 succeeded • 2 failed", controller.overviewText)
            states = [entry.status for entry in controller._model.entries()]
            self.assertEqual(states, ["Failed", "Failed"])
            controller.copyDetail(0)
            self.assertTrue(copied and "safety deadline" in copied[0])
            controller.openOutput(0)
            self.assertEqual(opened, [parent / "First"])

    def test_disconnecting_the_headset_skips_the_remaining_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "games"
            parent.mkdir()
            self._game(parent / "First", "com.example.first")
            snapshots = iter(
                [
                    DeviceSnapshot(True, "connected", "QUEST123", "Quest 3", 10**10),
                    DeviceSnapshot(False, "disconnected"),
                ]
            )
            last = DeviceSnapshot(False, "disconnected")

            def device() -> DeviceSnapshot:
                return next(snapshots, last)

            controller = BulkController(
                inspector=LocalBundleInspector(),
                analyzer=None,
                preflight_service=AutomaticPreflight(tools_ready=True),
                build_engine=SelectiveBuilder(),
                bundle_installer=ExplodingInstaller(),  # type: ignore[arg-type]
                settings_store=JsonSettingsStore(root / "settings.json"),
                device_snapshot=device,
            )
            controller.scanParent(QUrl.fromLocalFile(str(parent)))
            self._wait_until(lambda: controller.count == 1)

            controller.requestInstall()
            controller.confirmOperation()
            self._wait_until(lambda: controller.hasOverview)

            states = [entry.status for entry in controller._model.entries()]
            self.assertEqual(states, ["Skipped"])
            self.assertIn("Quest disconnected", controller.overviewText)


class LibrarySignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_selection_changes_do_not_rebuild_the_row_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apps = (
                __import__("quest_renamer.domain.models", fromlist=["InstalledQuestApp"])
                .InstalledQuestApp
            )
            library = LibraryController(
                GameLibraryStore(root / "library.json"),
                signing_root=root / "signing",
                installed_apps=lambda _serial: (
                    apps("com.a.one", "1"),
                    apps("com.b.two", "2"),
                    apps("com.c.three", "3"),
                ),
            )
            rows_signals: list[int] = []
            library.rowsChanged.connect(lambda: rows_signals.append(1))
            library.setDevice(DeviceSnapshot(True, "connected", "QUEST123", "Quest 3"))
            deadline = time.monotonic() + 3
            while library.isLoading or not library.count:
                self.application.processEvents()
                if time.monotonic() > deadline:
                    self.fail("inventory did not load")
                time.sleep(0.005)
            rows_before = len(rows_signals)

            library.select("com.b.two")
            library.selectOffset(1)
            self.assertEqual(library.selectedId, "com.c.three")
            library.selectOffset(5)
            self.assertEqual(library.selectedId, "com.c.three")
            library.selectOffset(-10)
            self.assertEqual(library.selectedId, "com.a.one")

            self.assertEqual(len(rows_signals), rows_before)
            library.setShowInstalled(False)
            self.assertEqual(len(rows_signals), rows_before + 1)


if __name__ == "__main__":
    unittest.main()


class DefaultTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_default_tag_drives_the_suggested_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = ControllerGuardTests._finished_folder(root, "Game")
            store = JsonSettingsStore(root / "settings.json")
            controller = AppController(
                settings_store=store,
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller.setDefaultTag(".mr")
            self.assertEqual(store.load().default_tag, "mr")

            controller.chooseFolder(QUrl.fromLocalFile(str(folder)))

            self.assertEqual(controller.packageId, "com.mr.example.game")
            controller.setDefaultTag("bad tag!")
            self.assertEqual(store.load().default_tag, "mr")


class StaticMonitor:
    def __init__(self) -> None:
        self.snapshot_value = DeviceSnapshot(False, "disconnected")

    def snapshot(self) -> DeviceSnapshot:
        return self.snapshot_value

    def set_preferred_serial(self, serial: str) -> None:
        self.preferred = serial

    def connect_wireless(self, address: str) -> str:
        return f"connected to {address}"

    def disconnect_wireless(self, address: str) -> str:
        return f"disconnected {address}"

    def enable_wireless(self, serial: str, *, port: int = 5555) -> str:
        return f"192.168.1.44:{port}"


class WirelessMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def _settle(self, controller: AppController) -> None:
        deadline = time.monotonic() + 3
        while controller._device_check_running:
            self.application.processEvents()
            if time.monotonic() >= deadline:
                self.fail("device poll did not finish")
            time.sleep(0.005)

    def test_successful_wireless_connections_are_remembered_and_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = JsonSettingsStore(root / "settings.json")
            controller = AppController(
                settings_store=store,
                device_service=StaticMonitor(),
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_wireless_outcome(
                ("connect", "192.168.1.44:5555", "connected to 192.168.1.44:5555", "")
            )
            self._settle(controller)
            controller._apply_device_snapshot(
                DeviceSnapshot(True, "connected", "192.168.1.44:5555", "Quest 3", 10**9)
            )

            saved = store.load().wireless_devices
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["address"], "192.168.1.44:5555")
            self.assertEqual(saved[0]["label"], "Quest 3")
            kinds = [entry["kind"] for entry in controller.deviceMenuEntries]
            self.assertIn("wireless", kinds)
            self.assertIn("disconnect", kinds)
            self.assertIn("Wi-Fi", controller.deviceLabel)
            wireless = next(e for e in controller.deviceMenuEntries if e["kind"] == "wireless")
            self.assertTrue(wireless["checked"])

            controller.renameWirelessDevice("192.168.1.44:5555", "Living room")
            self.assertEqual(store.load().wireless_devices[0]["label"], "Living room")
            controller.forgetWirelessDevice("192.168.1.44:5555")
            self.assertEqual(store.load().wireless_devices, [])
            self.assertIn("hint", [entry["kind"] for entry in controller.deviceMenuEntries])
            self._settle(controller)

    def test_saved_quests_keep_a_last_connection_stamp_and_can_be_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = JsonSettingsStore(root / "settings.json")
            controller = AppController(
                settings_store=store,
                device_service=StaticMonitor(),
                paths=AppPaths(data=root / "data", cache=root / "cache"),
            )
            controller._apply_wireless_outcome(
                ("enable", "192.168.1.9:5555", "Connected wirelessly at 192.168.1.9:5555.", "")
            )
            self._settle(controller)
            saved = store.load().wireless_devices
            self.assertEqual(saved[0]["address"], "192.168.1.9:5555")
            self.assertTrue(saved[0]["last_connected"])
            controller.forgetAllWirelessDevices()
            self.assertEqual(store.load().wireless_devices, [])
            self._settle(controller)
