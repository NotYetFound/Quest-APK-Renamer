import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quest_renamer.domain.installation import BundleInstallError, InstalledPackageConflict
from quest_renamer.domain.models import BundleDraft
from quest_renamer.infrastructure.adb_installer import AdbApkInstaller
from quest_renamer.infrastructure.process_runner import CommandResult


class BundleRunner:
    def __init__(self, remote_size: int, *, install_success: bool = True) -> None:
        self.remote_size = remote_size
        self.install_success = install_success
        self.commands: list[tuple[str, ...]] = []

    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        self.commands.append(command)
        if "install" in command:
            output = (
                ("Performing Streamed Install", "Success")
                if self.install_success
                else ("Performing Streamed Install", "Failure [INSTALL_FAILED]")
            )
        elif "stat" in command:
            output = (str(self.remote_size),)
        elif "pm" in command and "path" in command:
            output = ("package:/data/app/com.example.game/base.apk",)
        else:
            output = ()
        return CommandResult(command, 0, output)


class AdbInstallerTests(unittest.TestCase):
    def test_bundle_install_pushes_and_verifies_every_obb_and_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "main.42.com.example.game.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"obb-data")
            bundle = BundleDraft(
                root,
                apk,
                (obb,),
                package_name="com.example.game",
            )
            runner = BundleRunner(obb.stat().st_size)
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                result = installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            commands = ("\n".join(command) for command in runner.commands)
            combined = "\n".join(commands)
            self.assertIn("install\n-r\n-g", combined)
            self.assertIn("push", combined)
            self.assertIn("/sdcard/Android/obb/com.example.game", combined)
            self.assertIn("pm\npath\ncom.example.game", combined)
            self.assertTrue(result.package_verified)
            self.assertEqual(result.obbs[0].size, obb.stat().st_size)

    def test_bundle_install_rejects_a_remote_obb_size_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "main.42.com.example.game.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"obb-data")
            bundle = BundleDraft(
                root,
                apk,
                (obb,),
                package_name="com.example.game",
            )
            installer = AdbApkInstaller(  # type: ignore[arg-type]
                runner=BundleRunner(1)
            )

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaises(BundleInstallError) as raised,
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertEqual(raised.exception.failed_obbs, (obb,))

    def test_obb_retry_does_not_reinstall_the_apk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "main.42.com.example.game.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"obb-data")
            bundle = BundleDraft(
                root,
                apk,
                (obb,),
                package_name="com.example.game",
            )
            runner = BundleRunner(obb.stat().st_size)
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                result = installer.retry_obbs(bundle, "QUEST123")

            flattened = [part for command in runner.commands for part in command]
            self.assertNotIn("install", flattened)
            self.assertIn("push", flattened)
            self.assertTrue(result.package_verified)

    def test_bundle_install_requires_explicit_adb_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            adb.touch()
            apk.write_bytes(b"apk")
            bundle = BundleDraft(root, apk, package_name="com.example.game")
            installer = AdbApkInstaller(  # type: ignore[arg-type]
                runner=BundleRunner(0, install_success=False)
            )

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaises(BundleInstallError),
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

    def test_existing_package_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            adb.touch()
            apk.write_bytes(b"apk")
            bundle = BundleDraft(root, apk, package_name="com.example.game")
            runner = BundleRunner(0)
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaises(InstalledPackageConflict),
            ):
                installer.install_bundle(bundle, "QUEST123")

            flattened = [part for command in runner.commands for part in command]
            self.assertNotIn("install", flattened)


if __name__ == "__main__":
    unittest.main()
