import unittest
from pathlib import Path

from quest_renamer.infrastructure.legacy_file_picker import (
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
            Path("/tmp"),
        )
        self.assertIn("--multiple", command)
        self.assertIn("--separate-output", command)

    def test_zenity_save_command_requests_overwrite_confirmation(self) -> None:
        command = linux_picker_command(
            "/usr/bin/zenity",
            "save_json",
            "Export report",
            Path("/tmp"),
            "report.json",
        )
        self.assertIn("--save", command)
        self.assertIn("--confirm-overwrite", command)
        self.assertIn("--filename=/tmp/report.json", command)


if __name__ == "__main__":
    unittest.main()
