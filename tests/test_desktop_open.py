import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.desktop_open import (
    desktop_open_commands,
    external_process_environment,
    open_local_path,
)


class DesktopOpenTests(unittest.TestCase):
    def test_kde_prefers_native_openers_before_portal_fallbacks(self) -> None:
        path = Path("/games/Finished")

        commands = desktop_open_commands(
            path,
            platform_name="linux",
            environment={"XDG_CURRENT_DESKTOP": "KDE"},
        )

        self.assertEqual(commands[0], ("kioclient6", "exec", str(path)))
        self.assertIn(("xdg-open", str(path)), commands)

    def test_linux_falls_back_to_the_first_available_opener(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            launched: list[tuple[str, ...]] = []

            opened = open_local_path(
                folder,
                platform_name="linux",
                environment={"XDG_CURRENT_DESKTOP": "GNOME"},
                which=lambda command: "/usr/bin/xdg-open"
                if command == "xdg-open"
                else None,
                launcher=lambda command: launched.append(tuple(command)),
            )

            self.assertTrue(opened)
            self.assertEqual(launched, [("/usr/bin/xdg-open", str(folder.resolve()))])

    def test_missing_path_is_never_launched(self) -> None:
        launched: list[tuple[str, ...]] = []

        opened = open_local_path(
            Path("/definitely/missing/quest-renamer"),
            platform_name="linux",
            which=lambda _command: "/usr/bin/xdg-open",
            launcher=lambda command: launched.append(tuple(command)),
        )

        self.assertFalse(opened)
        self.assertEqual(launched, [])

    def test_packaged_library_paths_are_not_passed_to_host_file_managers(self) -> None:
        environment = {
            "APPIMAGE": "/tmp/Quest.AppImage",
            "LD_LIBRARY_PATH": "/tmp/appimage-libraries",
            "LD_LIBRARY_PATH_ORIG": "/usr/local/lib",
            "QT_PLUGIN_PATH": "/tmp/appimage-plugins",
            "QML2_IMPORT_PATH": "/tmp/appimage-qml",
            "XDG_CURRENT_DESKTOP": "KDE",
        }

        result = external_process_environment(environment)

        self.assertEqual(result["LD_LIBRARY_PATH"], "/usr/local/lib")
        self.assertNotIn("LD_LIBRARY_PATH_ORIG", result)
        self.assertNotIn("QT_PLUGIN_PATH", result)
        self.assertNotIn("QML2_IMPORT_PATH", result)
        self.assertEqual(result["XDG_CURRENT_DESKTOP"], "KDE")


if __name__ == "__main__":
    unittest.main()
