import subprocess
import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.adb_device import (
    AdbDeviceService,
    find_adb,
    parse_adb_devices,
    parse_available_storage,
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
        self.assertEqual(records[0].attributes["model"], "Quest 3")
        self.assertEqual(records[1].state, "unauthorized")

    def test_storage_parser_handles_android_df_output(self) -> None:
        output = (
            "Filesystem     1K-blocks    Used Available Use% Mounted on\n"
            "/dev/fuse       120000000 5000000 115000000   5% /storage/emulated\n"
        )
        self.assertEqual(parse_available_storage(output), 115_000_000 * 1024)

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

    def test_multiple_ready_devices_are_rejected(self) -> None:
        service = AdbDeviceService(
            adb=Path("/fake/adb"),
            run=lambda args, **_kwargs: completed(
                args,
                "List of devices attached\nONE device\nTWO device\n",
            ),
        )

        self.assertEqual(service.snapshot().status, "multiple")


if __name__ == "__main__":
    unittest.main()
