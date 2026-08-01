import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl

from quest_renamer.domain.build import BuildError, BuildResult, PackageRewriteReport
from quest_renamer.domain.installation import BundleInstallError, BundleInstallResult
from quest_renamer.domain.models import BuildRequest, BundleDraft, DeviceSnapshot
from quest_renamer.infrastructure.local_bundles import LocalBundleInspector
from quest_renamer.infrastructure.settings_store import JsonSettingsStore
from quest_renamer.presentation.bulk_controller import BulkController
from quest_renamer.services.preflight import AutomaticPreflight


class SelectiveBuilder:
    def __init__(self) -> None:
        self.packages: list[str] = []

    def build(self, request: BuildRequest, **_kwargs: object) -> BuildResult:
        self.packages.append(request.package_name)
        if "broken" in request.package_name:
            raise BuildError("simulated build failure")
        output = request.output_root
        output.mkdir(parents=True)
        apk = output / f"{request.package_name}.apk"
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


class SelectiveInstaller:
    def __init__(self) -> None:
        self.packages: list[str] = []

    def install_bundle(
        self,
        bundle: BundleDraft,
        _serial: str,
        **_kwargs: object,
    ) -> BundleInstallResult:
        self.packages.append(bundle.package_name)
        if "broken" in bundle.package_name:
            raise BundleInstallError("simulated install failure")
        return BundleInstallResult(bundle.package_name, bundle.apk, (), True)

    def retry_obbs(self, *_args: object, **_kwargs: object) -> BundleInstallResult:
        raise AssertionError("Bulk install should not call OBB retry automatically.")


class BulkControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_bulk_build_runs_sequentially_and_continues_after_one_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "games"
            parent.mkdir()
            self._game(parent / "First", "com.example.first")
            self._game(parent / "Broken", "com.example.broken")
            builder = SelectiveBuilder()
            controller = self._controller(root, builder=builder)

            controller.scanParent(QUrl.fromLocalFile(str(parent)))
            self._wait_until(lambda: controller.count == 2)
            controller.setSuffix("a")
            confirmations: list[str] = []
            controller.confirmationRequested.connect(
                lambda mode, _title, _body: confirmations.append(mode)
            )
            controller.requestBuild()
            self.assertEqual(confirmations, ["build"])
            controller.confirmOperation()
            self._wait_until(lambda: controller.hasOverview)

            self.assertEqual(
                builder.packages,
                ["com.example.brokena", "com.example.firsta"],
            )
            self.assertIn("1 succeeded • 1 failed", controller.overviewText)
            states = [entry.status for entry in controller._model.entries()]
            self.assertEqual(states, ["Failed", "Built"])

    def test_bulk_install_runs_every_item_and_reports_the_overview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "games"
            parent.mkdir()
            self._game(parent / "First", "com.example.first")
            self._game(parent / "Broken", "com.example.broken")
            installer = SelectiveInstaller()
            controller = self._controller(root, installer=installer)

            controller.scanParent(QUrl.fromLocalFile(str(parent)))
            self._wait_until(lambda: controller.count == 2)
            controller.requestInstall()
            controller.confirmOperation()
            self._wait_until(lambda: controller.hasOverview)

            self.assertEqual(
                installer.packages,
                ["com.example.broken", "com.example.first"],
            )
            self.assertIn("1 succeeded • 1 failed", controller.overviewText)

    def _controller(
        self,
        root: Path,
        *,
        builder: SelectiveBuilder | None = None,
        installer: SelectiveInstaller | None = None,
    ) -> BulkController:
        return BulkController(
            inspector=LocalBundleInspector(),
            analyzer=None,
            preflight_service=AutomaticPreflight(tools_ready=True),
            build_engine=builder or SelectiveBuilder(),
            bundle_installer=installer or SelectiveInstaller(),
            settings_store=JsonSettingsStore(root / "settings.json"),
            device_snapshot=lambda: DeviceSnapshot(
                True,
                "connected",
                "QUEST123",
                "Quest 3",
                10_000_000_000,
            ),
        )

    @staticmethod
    def _game(folder: Path, package: str) -> None:
        folder.mkdir()
        (folder / "game.apk").write_bytes(b"apk")
        (folder / "release.manifest").write_text(
            "Game Name;Release Name;Package Name;Version Code\n"
            f"{folder.name};{folder.name};{package};42\n",
            encoding="utf-8",
        )

    def _wait_until(self, condition: object) -> None:
        deadline = time.monotonic() + 2
        while not condition():  # type: ignore[operator]
            self.application.processEvents()
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for the bulk controller.")
            time.sleep(0.005)


if __name__ == "__main__":
    unittest.main()
