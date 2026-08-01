import unittest
from pathlib import Path, PurePosixPath
from subprocess import CompletedProcess

from quest_renamer.infrastructure.legacy_file_picker import (
    linux_desktop_pick,
    linux_dialog_order,
    linux_picker_command,
)


class LegacyFilePickerTests(unittest.TestCase):
    def test_desktop_specific_helper_order(self) -> None:
        self.assertEqual(linux_dialog_order({"XDG_CURRENT_DESKTOP": "KDE"})[0], "kdialog")
        self.assertEqual(
            linux_dialog_order({"XDG_CURRENT_DESKTOP": "GNOME"})[0],
            "zenity",
        )

    def test_kdialog_multi_apk_command_preserves_separate_paths(self) -> None:
        command = linux_picker_command(
            "/usr/bin/kdialog",
            "apks",
            "Choose APKs",
            PurePosixPath("/tmp"),
        )
        self.assertIn("--multiple", command)
        self.assertIn("--separate-output", command)

    def test_zenity_save_command_requests_overwrite_confirmation(self) -> None:
        command = linux_picker_command(
            "/usr/bin/zenity",
            "save_json",
            "Export report",
            PurePosixPath("/tmp"),
            "report.json",
        )
        self.assertIn("--save", command)
        self.assertIn("--confirm-overwrite", command)
        self.assertIn("--filename=/tmp/report.json", command)

    def test_desktop_picker_uses_clean_host_environment(self) -> None:
        received_environment: dict[str, str] = {}

        def runner(arguments: list[str], **kwargs: object) -> CompletedProcess[str]:
            received_environment.update(kwargs["env"])  # type: ignore[arg-type]
            return CompletedProcess(arguments, 0, stdout="/tmp/game\n", stderr="")

        result = linux_desktop_pick(
            "folder",
            "Choose",
            Path("/tmp"),
            "",
            environment={
                "XDG_CURRENT_DESKTOP": "KDE",
                "APPIMAGE": "/tmp/app.AppImage",
                "LD_LIBRARY_PATH": "/tmp/bundled",
                "QT_PLUGIN_PATH": "/tmp/plugins",
            },
            which=lambda name: f"/usr/bin/{name}" if name == "kdialog" else None,
            runner=runner,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.paths, (Path("/tmp/game"),))
        self.assertNotIn("LD_LIBRARY_PATH", received_environment)
        self.assertNotIn("QT_PLUGIN_PATH", received_environment)


if __name__ == "__main__":
    unittest.main()
