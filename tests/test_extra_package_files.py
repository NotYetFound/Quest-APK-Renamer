import shlex
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_adb_installer import MemoryQuestRunner

from quest_renamer.domain.installation import BundleInstallError, BundleInstallResult
from quest_renamer.domain.models import BuildRequest, BundleDraft, DeviceSnapshot
from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure.adb_installer import AdbApkInstaller
from quest_renamer.infrastructure.app_paths import AppPaths
from quest_renamer.infrastructure.local_bundles import LocalBundleInspector
from quest_renamer.presentation.app_controller import AppController, InstallOutcome
from quest_renamer.services.preflight import AutomaticPreflight


class ExtraFilesTests(unittest.TestCase):
    def test_capacity_check_includes_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            data = root / "com.example.game"
            data.mkdir()
            extra = data / "large.dat"
            with extra.open("wb") as handle:
                handle.truncate(16 * 1024 * 1024)
            request = BuildRequest(
                BundleDraft(root, apk, package_name=data.name),
                "com.dev.example.game",
                root.parent / "capacity-output",
            )
            free = 136 * 1024 * 1024
            result = AutomaticPreflight(tools_ready=True).check(
                request, device=DeviceSnapshot(True, serial="QUEST", free_bytes=free)
            )
            quest = next(check for check in result.checks if check.key == "quest_space")
            self.assertEqual(quest.state.value, "warning")
            self.assertGreater(result.quest_required_bytes, free)

    def test_extra_hash_failure_preserves_old_file_and_quoted_names_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            adb.touch()
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            data = root / "com.example.game"
            data.mkdir()
            extra = data / "data 'file;$.bin"
            extra.write_bytes(b"correct")
            bundle = BundleDraft(root, apk, package_name=data.name)
            destination = f"/sdcard/Android/obb/{data.name}/{extra.name}"
            remote = {destination: b"old"}
            runner = MemoryQuestRunner(remote, corrupt_obb_during_push=True)
            original = runner.run

            def remote_shell(arguments: object, **kwargs: object) -> object:
                command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
                if "shell" in command:
                    command = tuple(
                        shlex.split(value)[0] if value.startswith("'") else value
                        for value in command
                    )
                return original(command, **kwargs)

            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            with (
                patch.dict("os.environ", {"QAR_ADB": str(adb)}),
                patch.object(runner, "run", side_effect=remote_shell),
            ):
                with self.assertRaises(BundleInstallError) as failure:
                    installer.install_bundle(bundle, "QUEST", allow_existing=True)
                self.assertEqual(failure.exception.failed_extra_files, (extra,))
                self.assertEqual(remote[destination], b"old")
                self.assertFalse(any(".qar-new-" in path for path in remote))
                runner.corrupt_obb_during_push = False
                installer.retry_obbs(bundle, "QUEST")
                self.assertEqual(remote[destination], b"correct")

    def test_discovery_scopes_files_counts_bytes_and_rejects_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            data = root / "com.example.game"
            (data / "nested").mkdir(parents=True)
            extra = data / "nested" / "data.bin"
            extra.write_bytes(b"data")
            (root / "readme.txt").write_bytes(b"not game data")
            (data / "main.obb").write_bytes(b"obb")
            bundle = BundleDraft(root, apk, package_name=data.name)
            self.assertEqual(bundle.extra_files, (extra,))
            self.assertEqual(bundle.total_size, 7)
            with self.assertRaises(ValueError):
                _ = replace(bundle, package_name="../elsewhere").extra_files
            with self.assertRaises(ValueError):
                _ = replace(bundle, auxiliary_files=(data / ".." / "readme.txt",)).extra_files
            with self.assertRaises(ValueError):
                _ = replace(bundle, auxiliary_files=(root / "readme.txt",)).extra_files
            try:
                (data / "linked").symlink_to(root, target_is_directory=True)
                (data / "link.txt").symlink_to(root / "readme.txt")
            except OSError:
                return  # Windows may require Developer Mode to create symlinks.
            self.assertEqual(bundle.extra_files, (extra,))
            with self.assertRaises(ValueError):
                _ = replace(bundle, auxiliary_files=(data / "link.txt",)).extra_files

    def test_failure_retry_cancellation_and_identical_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb"
            adb.touch()
            apk = root / "game.apk"
            apk.write_bytes(b"apk")
            data = root / "com.example.game"
            data.mkdir()
            first, second = data / "a.dat", data / "b.dat"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            bundle = BundleDraft(root, apk, package_name=data.name)
            base = f"/sdcard/Android/obb/{data.name}"
            remote = {f"{base}/b.dat": b"old", f"{base}/unrelated": b"keep"}
            runner = MemoryQuestRunner(remote)
            installer = AdbApkInstaller(runner=runner)  # type: ignore[arg-type]
            original = runner.run

            def fail_second(arguments: object, **kwargs: object) -> object:
                result = original(arguments, **kwargs)
                command = tuple(str(value) for value in arguments)  # type: ignore[union-attr]
                if "push" in command and command[-2] == str(second):
                    raise RuntimeError("Cable disconnected after upload")
                return result

            with patch.dict("os.environ", {"QAR_ADB": str(adb)}):
                with (
                    patch.object(runner, "run", side_effect=fail_second),
                    self.assertRaises(BundleInstallError) as failure,
                ):
                    installer.install_bundle(bundle, "QUEST", allow_existing=True)
                self.assertTrue(failure.exception.apk_installed)
                self.assertEqual(failure.exception.failed_extra_files, (second,))
                self.assertEqual(remote[f"{base}/a.dat"], b"first")
                self.assertEqual(remote[f"{base}/b.dat"], b"old")
                self.assertFalse(any(".qar-new-" in path for path in remote))
                runner.commands.clear()
                installer.retry_obbs(replace(bundle, auxiliary_files=(second,)), "QUEST")
                self.assertFalse(any("install" in command for command in runner.commands))
                pushes = [command[-2] for command in runner.commands if "push" in command]
                self.assertEqual(pushes, [str(second)])
                self.assertEqual(remote[f"{base}/b.dat"], b"second")
                self.assertEqual(remote[f"{base}/unrelated"], b"keep")
                runner.commands.clear()
                installer.retry_obbs(bundle, "QUEST")
                self.assertFalse(any("push" in command for command in runner.commands))

                remote[f"{base}/b.dat"] = b"old"
                token = CancellationToken()

                def cancel_upload(arguments: object, **kwargs: object) -> object:
                    result = original(arguments, **kwargs)
                    if "push" in tuple(str(value) for value in arguments):  # type: ignore[union-attr]
                        token.cancel()
                    return result

                with (
                    patch.object(runner, "run", side_effect=cancel_upload),
                    self.assertRaises(OperationCancelled),
                ):
                    installer.retry_obbs(bundle, "QUEST", token=token)
                self.assertEqual(remote[f"{base}/b.dat"], b"old")
                self.assertFalse(any(".qar-new-" in path for path in remote))

    def test_controller_keeps_source_until_extra_retry_succeeds(self) -> None:
        from test_controller_guards import ControllerGuardTests

        helper = ControllerGuardTests()
        helper.setUpClass()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = helper._finished_folder(root)
            bundle = LocalBundleInspector().inspect_folder(folder)
            extra = bundle.root / bundle.package_name / "data.bin"
            extra.parent.mkdir(exist_ok=True)
            extra.write_bytes(b"data")
            controller = AppController(paths=AppPaths(data=root / "data", cache=root / "cache"))
            controller._device = DeviceSnapshot(True, serial="QUEST")
            controller._install_generation = 1
            # A previous failed game must not become the successful retry's source.
            controller._retry_full_bundle = replace(bundle, root=root / "another-game")
            with patch.object(controller, "_delete_source_after_verified_install") as delete:
                controller._apply_install_outcome(
                    1,
                    InstallOutcome(
                        bundle,
                        error="transfer failed",
                        failed_extra_files=(extra,),
                        apk_installed=True,
                    ),
                )
                delete.assert_not_called()
                self.assertTrue(controller.canRetryObbs)
                self.assertEqual(controller._retry_full_bundle, bundle)
                self.assertEqual(controller.retryFilesLabel, "Retry failed extra files")
                retry = controller._retry_bundle
                assert retry is not None
                self.assertEqual(retry.obbs, ())
                self.assertEqual(retry.extra_files, (extra,))
                controller._library_controller = None
                controller._apply_install_outcome(
                    1,
                    InstallOutcome(
                        retry,
                        result=BundleInstallResult(bundle.package_name, bundle.apk, (), True),
                    ),
                )
                delete.assert_called_once()
