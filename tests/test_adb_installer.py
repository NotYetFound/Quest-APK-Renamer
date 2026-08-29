import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quest_renamer.domain.installation import BundleInstallError, InstalledPackageConflict
from quest_renamer.domain.models import BundleDraft
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
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
        install_failure_line: str = "",
    ) -> None:
        self.remote = remote
        self.install_success = install_success
        self.install_failure_line = install_failure_line
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
            output = (
                ("Success",)
                if self.install_success
                else (self.install_failure_line or "Failure [INSTALL_FAILED]",)
            )
            return CommandResult(command, 0 if self.install_success else 1, output)
        if "pm" in command and "path" in command:
            return (
                CommandResult(command, 0, ("package:/data/app/example/base.apk",))
                if self.package_verify_success
                else CommandResult(command, 1, ())
            )
        if "ls" in command and any(arg.startswith("-1") for arg in command):
            root = command[-1].rstrip("/") + "/"
            show_hidden = any(arg.startswith("-1") and "a" in arg for arg in command)
            names = sorted(
                path.removeprefix(root)
                for path in self.remote
                if path.startswith(root)
                and "/" not in path.removeprefix(root)
                and (show_hidden or not path.removeprefix(root).startswith("."))
            )
            return CommandResult(command, 0, tuple(names))
        if "stat" in command and command[-1].endswith("/*"):
            # Batched listing: ``stat -c %s:%n dir/*`` expanded by the remote shell.
            root = command[-1][:-1]
            rows = tuple(
                f"{len(data)}:{path}"
                for path, data in sorted(self.remote.items())
                if path.startswith(root)
                and "/" not in path.removeprefix(root)
                and not path.removeprefix(root).startswith(".")
            )
            return CommandResult(command, 0 if rows else 1, rows)
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
            for path in command[command.index("-f") + 1 :]:
                self.remote.pop(path, None)
            return CommandResult(command, 0, ())
        if "uninstall" in command:
            return CommandResult(command, 0, ("Success",))
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


class InstallSafetyTests(unittest.TestCase):
    def _bundle_files(self, root: Path, *obb_names: str) -> tuple[Path, tuple[Path, ...]]:
        adb = root / "adb"
        adb.touch()
        apk = root / "game.apk"
        apk.write_bytes(b"apk")
        obbs = []
        for name in obb_names:
            obb = root / name
            obb.write_bytes(f"data for {name}".encode())
            obbs.append(obb)
        return adb, tuple(obbs)

    def test_apk_only_install_leaves_existing_quest_obbs_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb, _ = self._bundle_files(root)
            remote_root = "/sdcard/Android/obb/com.example.game"
            runner = MemoryQuestRunner(
                {
                    f"{remote_root}/main.47.com.example.game.obb": b"keep me",
                    f"{remote_root}/patch.47.com.example.game.obb": b"keep me too",
                }
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, root / "game.apk", package_name="com.example.game")

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertEqual(len(runner.remote), 2)
            self.assertIn(f"{remote_root}/main.47.com.example.game.obb", runner.remote)

    def test_obb_retry_only_prunes_outside_the_kept_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb, obbs = self._bundle_files(
                root, "main.48.com.example.game.obb", "patch.48.com.example.game.obb"
            )
            remote_root = "/sdcard/Android/obb/com.example.game"
            runner = MemoryQuestRunner(
                {
                    f"{remote_root}/patch.48.com.example.game.obb": obbs[1].read_bytes(),
                    f"{remote_root}/main.40.com.example.game.obb": b"obsolete",
                }
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            retry_bundle = BundleDraft(
                root, root / "game.apk", (obbs[0],), package_name="com.example.game"
            )

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                installer.retry_obbs(
                    retry_bundle,
                    "QUEST123",
                    keep_obb_names=tuple(obb.name for obb in obbs),
                )

            self.assertIn(f"{remote_root}/main.48.com.example.game.obb", runner.remote)
            self.assertIn(f"{remote_root}/patch.48.com.example.game.obb", runner.remote)
            self.assertNotIn(f"{remote_root}/main.40.com.example.game.obb", runner.remote)

    def test_obb_retry_without_kept_set_never_prunes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb, obbs = self._bundle_files(root, "main.48.com.example.game.obb")
            remote_root = "/sdcard/Android/obb/com.example.game"
            runner = MemoryQuestRunner(
                {f"{remote_root}/patch.48.com.example.game.obb": b"other file"}
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, root / "game.apk", obbs, package_name="com.example.game")

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                installer.retry_obbs(bundle, "QUEST123")

            self.assertIn(f"{remote_root}/patch.48.com.example.game.obb", runner.remote)
            self.assertIn(f"{remote_root}/main.48.com.example.game.obb", runner.remote)

    def test_install_failures_are_classified_for_the_user(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb, _ = self._bundle_files(root)
            runner = MemoryQuestRunner(
                {},
                install_success=False,
                install_failure_line=(
                    "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Existing package "
                    "signatures do not match newer version]"
                ),
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, root / "game.apk", package_name="com.example.game")

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaises(BundleInstallError) as raised,
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertIn("different key", str(raised.exception))
            self.assertFalse(raised.exception.apk_installed)

    def test_same_size_remote_obbs_are_hashed_once_each(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb, obbs = self._bundle_files(
                root,
                "main.50.com.example.game.obb",
                "patch.50.com.example.game.obb",
            )
            remote_root = "/sdcard/Android/obb/com.example.game"
            same_size = b"x" * len(obbs[0].read_bytes())
            runner = MemoryQuestRunner(
                {
                    f"{remote_root}/main.49.com.example.game.obb": same_size,
                    f"{remote_root}/patch.49.com.example.game.obb": same_size,
                    f"{remote_root}/other.49.com.example.game.obb": same_size,
                }
            )
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, root / "game.apk", obbs, package_name="com.example.game")

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            hashed = [command[-1] for command in runner.commands if "sha256sum" in command]
            self.assertEqual(len(hashed), len(set(hashed)))

    def test_stale_staging_files_are_removed_even_though_they_are_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb, obbs = self._bundle_files(root, "main.51.com.example.game.obb")
            remote_root = "/sdcard/Android/obb/com.example.game"
            stale = f"{remote_root}/.qar-new-0123456789ab-1-main.51.com.example.game.obb"
            runner = MemoryQuestRunner({stale: b"left over"})
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, root / "game.apk", obbs, package_name="com.example.game")

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertNotIn(stale, runner.remote)
            listing = [command for command in runner.commands if "ls" in command]
            self.assertTrue(any("-1a" in command for command in listing))

    def test_post_install_verification_failure_reports_apk_installed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb, obbs = self._bundle_files(root, "main.52.com.example.game.obb")
            runner = MemoryQuestRunner({}, corrupt_obb_after_install=True)
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, root / "game.apk", obbs, package_name="com.example.game")

            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                self.assertRaises(BundleInstallError) as raised,
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertTrue(raised.exception.apk_installed)
            self.assertEqual(raised.exception.failed_obbs, obbs)


class CancellingQuestRunner(MemoryQuestRunner):
    """Cancels ``token`` the first time a command matches ``trigger``."""

    def __init__(
        self, remote: dict[str, bytes], token: CancellationToken, trigger: str
    ) -> None:
        super().__init__(remote)
        self.token = token
        self.trigger = trigger
        self.fired = False

    def run(self, arguments: object, **kwargs: object) -> CommandResult:
        result = super().run(arguments, **kwargs)
        command = " ".join(str(value) for value in arguments)  # type: ignore[union-attr]
        if not self.fired and self.trigger in command:
            self.fired = True
            self.token.cancel()
        return result


class InstallTransactionTests(unittest.TestCase):
    def _files(self, root: Path, *names: str) -> tuple[Path, tuple[Path, ...]]:
        (root / "adb").touch()
        apk = root / "game.apk"
        apk.write_bytes(b"apk")
        obbs = []
        for name in names:
            path = root / name
            path.write_bytes(f"new-{name}".encode())
            obbs.append(path)
        return apk, tuple(obbs)

    def test_cancel_during_cleanup_keeps_the_verified_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk, obbs = self._files(root, "main.2.com.example.game.obb")
            remote_path = "/sdcard/Android/obb/com.example.game/main.2.com.example.game.obb"
            token = CancellationToken()
            # Fire the cancel when the verified transaction removes its backup.
            runner = CancellingQuestRunner({remote_path: b"old"}, token, "rm -f " + remote_path)
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, apk, obbs, package_name="com.example.game")

            with patch.dict("os.environ", {"QAR_ADB": str(root / "adb")}):
                result = installer.install_bundle(
                    bundle, "QUEST123", allow_existing=True, token=token
                )

            self.assertTrue(result.package_verified)
            self.assertEqual(runner.remote[remote_path], b"new-main.2.com.example.game.obb")
            self.assertFalse(any(".qar-" in path for path in runner.remote))

    def test_cancel_between_the_two_activation_moves_restores_the_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk, obbs = self._files(root, "main.2.com.example.game.obb")
            remote_path = "/sdcard/Android/obb/com.example.game/main.2.com.example.game.obb"
            token = CancellationToken()
            runner = CancellingQuestRunner({remote_path: b"old"}, token, ".qar-old-")
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, apk, obbs, package_name="com.example.game")

            with (
                patch.dict("os.environ", {"QAR_ADB": str(root / "adb")}),
                self.assertRaises((OperationCancelled, BundleInstallError)),
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True, token=token)

            self.assertEqual(runner.remote, {remote_path: b"old"})

    def test_rollback_after_activation_reports_every_removed_obb_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk, obbs = self._files(
                root, "main.2.com.example.game.obb", "patch.2.com.example.game.obb"
            )
            runner = MemoryQuestRunner({}, corrupt_obb_after_install=True)
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, apk, obbs, package_name="com.example.game")

            with (
                patch.dict("os.environ", {"QAR_ADB": str(root / "adb")}),
                self.assertRaises(BundleInstallError) as caught,
            ):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertTrue(caught.exception.apk_installed)
            self.assertEqual(set(caught.exception.failed_obbs), set(obbs))
            self.assertFalse(any(path.endswith(".obb") for path in runner.remote))

    def test_obb_parked_by_an_interrupted_install_is_restored_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk, obbs = self._files(root, "main.2.com.example.game.obb")
            remote_root = "/sdcard/Android/obb/com.example.game"
            parked = f"{remote_root}/main.2.com.example.game.obb.qar-old-abc123-1"
            runner = MemoryQuestRunner({parked: b"old"})
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            bundle = BundleDraft(root, apk, obbs, package_name="com.example.game")

            with patch.dict("os.environ", {"QAR_ADB": str(root / "adb")}):
                installer.install_bundle(bundle, "QUEST123", allow_existing=True)

            self.assertIn(
                ("shell", "mv", parked, f"{remote_root}/main.2.com.example.game.obb"),
                [command[-4:] for command in runner.commands],
            )
            self.assertEqual(
                runner.remote,
                {
                    f"{remote_root}/main.2.com.example.game.obb": (
                        b"new-main.2.com.example.game.obb"
                    )
                },
            )


if __name__ == "__main__":
    unittest.main()
