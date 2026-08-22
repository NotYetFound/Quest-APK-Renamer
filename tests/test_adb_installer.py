import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quest_renamer.domain.installation import BundleInstallError, InstalledPackageConflict
from quest_renamer.domain.models import BundleDraft
from quest_renamer.domain.operations import CancellationToken
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


class MemoryQuestRunner:
    def __init__(
        self,
        remote: dict[str, bytes],
        *,
        install_success: bool = True,
        package_verify_success: bool = True,
        corrupt_obb_after_install: bool = False,
    ) -> None:
        self.remote = remote
        self.install_success = install_success
        self.package_verify_success = package_verify_success
        self.corrupt_obb_after_install = corrupt_obb_after_install
        self.commands: list[tuple[str, ...]] = []

    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
        self.commands.append(command)
        if "push" in command:
            index = command.index("push")
            self.remote[command[index + 2]] = Path(command[index + 1]).read_bytes()
            return CommandResult(command, 0, ())
        if "install" in command:
            if self.install_success and self.corrupt_obb_after_install:
                for path in tuple(self.remote):
                    if path.endswith(".obb") and ".qar-" not in path:
                        self.remote[path] += b"corrupt"
            output = ("Success",) if self.install_success else ("Failure [INSTALL_FAILED]",)
            return CommandResult(command, 0, output)
        if "pm" in command and "path" in command:
            return (
                CommandResult(command, 0, ("package:/data/app/example/base.apk",))
                if self.package_verify_success
                else CommandResult(command, 1, ())
            )
        if "ls" in command and "-1" in command:
            root = command[-1].rstrip("/") + "/"
            names = sorted(
                path.removeprefix(root)
                for path in self.remote
                if path.startswith(root) and "/" not in path.removeprefix(root)
            )
            return CommandResult(command, 0, tuple(names))
        if "stat" in command:
            data = self.remote.get(command[-1])
            return (
                CommandResult(command, 0 if data is not None else 1, ())
                if data is None
                else CommandResult(command, 0, (str(len(data)),))
            )
        if "sha256sum" in command:
            data = self.remote.get(command[-1])
            output = (
                (f"{hashlib.sha256(data).hexdigest()}  {command[-1]}",)
                if data is not None
                else ()
            )
            return CommandResult(command, 0 if data is not None else 1, output)
        if "mv" in command:
            source, destination = command[-2:]
            if source in self.remote:
                self.remote[destination] = self.remote.pop(source)
            return CommandResult(command, 0, ())
        if "rm" in command and "-f" in command:
            self.remote.pop(command[-1], None)
            return CommandResult(command, 0, ())
        return CommandResult(command, 0, ())


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

    def test_update_reuses_identical_versioned_obb_without_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "main.47.com.example.game.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"same expansion data")
            remote_root = "/sdcard/Android/obb/com.example.game"
            old_path = f"{remote_root}/main.42.com.example.game.obb"
            new_path = f"{remote_root}/{obb.name}"
            unknown_path = f"{remote_root}/developer-notes.obb"
            runner = MemoryQuestRunner(
                {
                    old_path: obb.read_bytes(),
                    unknown_path: b"preserve unknown files",
                }
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(
                root,
                apk,
                (obb,),
                package_name="com.example.game",
                version_code="47",
            )

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                result = installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertNotIn(old_path, runner.remote)
            self.assertEqual(runner.remote[new_path], obb.read_bytes())
            self.assertIn(unknown_path, runner.remote)
            self.assertFalse(any("push" in command for command in runner.commands))
            self.assertEqual(result.obbs[0].action, "renamed on Quest")

    def test_verified_update_removes_stale_pakchunk_for_the_same_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "patch.pakchunk0-Android_ASTC.com.example.game.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"new chunk")
            remote_root = "/sdcard/Android/obb/com.example.game"
            current = f"{remote_root}/{obb.name}"
            stale = (
                f"{remote_root}/"
                "patch.pakchunk0-Android_ETC2.com.example.game.obb"
            )
            unrelated = f"{remote_root}/patch.pakchunk0-Android_ASTC.com.other.game.obb"
            runner = MemoryQuestRunner({stale: b"old chunk", unrelated: b"other"})
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(
                root,
                apk,
                (obb,),
                package_name="com.example.game",
            )

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertEqual(runner.remote[current], b"new chunk")
            self.assertNotIn(stale, runner.remote)
            self.assertIn(unrelated, runner.remote)

    def test_failed_apk_update_restores_the_previous_nonversioned_obb(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "game-data.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"new-data")
            remote_path = "/sdcard/Android/obb/com.example.game/game-data.obb"
            runner = MemoryQuestRunner(
                {remote_path: b"old-data"},
                install_success=False,
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, apk, (obb,), package_name="com.example.game")

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaises(BundleInstallError),
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertEqual(runner.remote[remote_path], b"old-data")
            self.assertFalse(any(".qar-new-" in path for path in runner.remote))
            self.assertFalse(any(".qar-old-" in path for path in runner.remote))

    def test_failed_package_verification_after_apk_success_restores_previous_obb(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "game-data.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"new-data")
            remote_path = "/sdcard/Android/obb/com.example.game/game-data.obb"
            runner = MemoryQuestRunner(
                {remote_path: b"old-data"},
                package_verify_success=False,
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, apk, (obb,), package_name="com.example.game")

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaisesRegex(BundleInstallError, "did not report"),
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertEqual(runner.remote[remote_path], b"old-data")
            self.assertFalse(any(".qar-new-" in path for path in runner.remote))
            self.assertFalse(any(".qar-old-" in path for path in runner.remote))

    def test_failed_obb_verification_can_be_retried_without_backup_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            apk = root / "game.apk"
            obb = root / "game-data.obb"
            adb.touch()
            apk.write_bytes(b"apk")
            obb.write_bytes(b"new-data")
            remote_path = "/sdcard/Android/obb/com.example.game/game-data.obb"
            runner = MemoryQuestRunner(
                {remote_path: b"old-data"},
                corrupt_obb_after_install=True,
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, apk, (obb,), package_name="com.example.game")

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaisesRegex(BundleInstallError, "wrong size"),
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertEqual(runner.remote[remote_path], b"old-data")
            runner.corrupt_obb_after_install = False
            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                installer.retry_obbs(bundle, "QUEST123")

            self.assertEqual(runner.remote[remote_path], b"new-data")
            self.assertFalse(any(".qar-" in path for path in runner.remote))

    def test_local_obb_hash_is_reused_until_the_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            obb = Path(temporary) / "main.1.com.example.game.obb"
            obb.write_bytes(b"first OBB payload")
            installer = AdbApkInstaller()
            token = CancellationToken()

            with patch(
                "quest_renamer.infrastructure.adb_installer.hashlib.sha256",
                wraps=hashlib.sha256,
            ) as sha256:
                first = installer._local_sha256(obb, token)
                second = installer._local_sha256(obb, token)
                obb.write_bytes(b"a different and longer OBB payload")
                changed = installer._local_sha256(obb, token)

            self.assertEqual(first, second)
            self.assertNotEqual(first, changed)
            self.assertEqual(sha256.call_count, 2)


if __name__ == "__main__":
    unittest.main()
