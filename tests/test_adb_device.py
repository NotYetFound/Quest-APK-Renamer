import subprocess
import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.adb_device import (
    AdbDeviceService,
    find_adb,
    parse_adb_devices,
    parse_available_storage,
    parse_package_versions,
    parse_user_package_versions,
    parse_user_packages,
)


def completed(
    arguments: list[str],
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(arguments, returncode, stdout, stderr)


class AdbDeviceTests(unittest.TestCase):
    def test_device_parser_preserves_state_and_model(self) -> None:
        records = parse_adb_devices(
            "List of devices attached\n"
            "QUEST123 device product:eureka model:Quest_3 device:eureka\n"
            "QUEST456 unauthorized usb:1-3\n"
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].serial, "QUEST123")
        self.assertEqual(records[0].attributes["model"], "Quest_3")
        chatter = parse_adb_devices(
            "adb server version (41) doesn't match this client (39); killing...\n"
            "* daemon started successfully\n"
            "List of devices attached\n"
        )
        self.assertEqual(chatter, ())
        self.assertEqual(records[1].state, "unauthorized")

    def test_storage_parser_handles_android_df_output(self) -> None:
        output = (
            "Filesystem     1K-blocks    Used Available Use% Mounted on\n"
            "/dev/fuse       120000000 5000000 115000000   5% /storage/emulated\n"
        )
        self.assertEqual(parse_available_storage(output), 115_000_000 * 1024)

    def test_user_package_parser_filters_noise_and_sorts(self) -> None:
        packages = parse_user_packages(
            "package:com.zeta.game\n"
            "adb: warning\n"
            "package:com.alpha.game\r\n"
            "package:not-a-package\n"
        )

        self.assertEqual(packages, ("com.alpha.game", "com.zeta.game"))

    def test_package_list_parser_reads_inline_version_codes(self) -> None:
        self.assertEqual(
            parse_user_package_versions(
                "package:com.example.two versionCode:20\n"
                "package:com.example.one versionCode:10 minSdk:29\n"
            ),
            {"com.example.two": "20", "com.example.one": "10"},
        )

    def test_package_version_parser_reads_requested_package_blocks(self) -> None:
        versions = parse_package_versions(
            "Package [com.alpha.game] (123):\n"
            "  versionCode=42 minSdk=29 targetSdk=32\n"
            "  versionName=1.2.0\n"
            "Package [android] (1):\n"
            "  versionCode=99\n"
            "Package [com.zeta.game] (456):\n"
            "  versionCode=7\n"
            "  versionName=null\n",
            {"com.alpha.game", "com.zeta.game"},
        )

        self.assertEqual(versions["com.alpha.game"], ("42", "1.2.0"))
        self.assertEqual(versions["com.zeta.game"], ("7", ""))

    def test_adb_override_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adb = Path(temporary) / "adb"
            adb.touch()
            result = find_adb(
                environment={"QAR_ADB": str(adb)},
                home=Path(temporary),
                system="linux",
                which=lambda _name: None,
            )
        self.assertEqual(result, adb.resolve())

    def test_unauthorized_headset_has_actionable_status(self) -> None:
        service = AdbDeviceService(
            adb=Path("/fake/adb"),
            run=lambda args, **_kwargs: completed(
                args,
                "List of devices attached\nQUEST123 unauthorized usb:1-2\n",
            ),
        )

        snapshot = service.snapshot()

        self.assertEqual(snapshot.status, "unauthorized")
        self.assertIn("approve USB debugging", snapshot.detail)

    def test_linux_permission_problem_is_distinct_from_disconnected(self) -> None:
        service = AdbDeviceService(
            adb=Path("/fake/adb"),
            run=lambda args, **_kwargs: completed(
                args,
                "List of devices attached\n"
                "QUEST123 no permissions (user in plugdev group; are your udev rules wrong?)\n",
            ),
        )

        snapshot = service.snapshot()

        self.assertEqual(snapshot.status, "permission")
        self.assertIn("udev", snapshot.detail)

    def test_connected_headset_reports_model_and_free_space(self) -> None:
        def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if args[-2:] == ["getprop", "ro.product.model"]:
                return completed(args, "Meta Quest 3\n")
            if "df" in args:
                return completed(
                    args,
                    "Filesystem 1K-blocks Used Available Use% Mounted on\n"
                    "/dev/fuse 120000000 20000000 100000000 17% /sdcard\n",
                )
            return completed(
                args,
                "List of devices attached\n"
                "QUEST123 device product:eureka model:Quest_3 device:eureka\n",
            )

        snapshot = AdbDeviceService(adb=Path("/fake/adb"), run=fake_run).snapshot()

        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.model, "Meta Quest 3")
        self.assertEqual(snapshot.free_bytes, 100_000_000 * 1024)

    def test_repeated_snapshot_reuses_the_model_for_the_same_serial(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if args[-2:] == ["getprop", "ro.product.model"]:
                return completed(args, "Meta Quest 3\n")
            if "df" in args:
                return completed(args, "/dev/fuse 100 20 80 20% /sdcard\n")
            return completed(args, "List of devices attached\nQUEST123 device\n")

        service = AdbDeviceService(adb=Path("/fake/adb"), run=fake_run)

        service.snapshot()
        service.snapshot()

        model_calls = [args for args in calls if "ro.product.model" in args]
        self.assertEqual(len(model_calls), 1)

    def test_multiple_ready_devices_are_rejected(self) -> None:
        service = AdbDeviceService(
            adb=Path("/fake/adb"),
            run=lambda args, **_kwargs: completed(
                args,
                "List of devices attached\nONE device\nTWO device\n",
            ),
        )

        self.assertEqual(service.snapshot().status, "multiple")

    def test_installed_apps_uses_one_call_when_version_codes_are_supported(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return completed(
                args,
                "package:com.example.one versionCode:10\n"
                "package:com.example.two versionCode:20\n",
            )

        apps = AdbDeviceService(adb=Path("/fake/adb"), run=fake_run).installed_apps(
            "QUEST123"
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual([app.package_name for app in apps], [
            "com.example.one",
            "com.example.two",
        ])
        self.assertEqual(apps[1].version_code, "20")

    def test_installed_apps_falls_back_to_one_bulk_dumpsys_on_older_pm(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if "list" in args:
                return completed(
                    args,
                    "package:com.example.one\npackage:com.example.two\n",
                )
            return completed(
                args,
                "Package [com.example.one] (1):\n"
                "  versionCode=10\n"
                "  versionName=1.0\n"
                "Package [com.example.two] (2):\n"
                "  versionCode=20\n"
                "  versionName=2.0\n",
            )

        apps = AdbDeviceService(adb=Path("/fake/adb"), run=fake_run).installed_apps(
            "QUEST123"
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(apps[0].version_name, "1.0")

    def test_installed_apps_handles_old_pm_reporting_unknown_option_as_success(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if "--show-versioncode" in args:
                return completed(args, "Error: Unknown option: --show-versioncode\n")
            if "list" in args:
                return completed(args, "package:com.example.game\n")
            return completed(
                args,
                "Package [com.example.game] (1):\n  versionCode=42\n",
            )

        apps = AdbDeviceService(adb=Path("/fake/adb"), run=fake_run).installed_apps(
            "QUEST123"
        )

        self.assertEqual(len(calls), 3)
        self.assertEqual(apps[0].version_code, "42")


if __name__ == "__main__":
    unittest.main()
