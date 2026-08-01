import unittest
from pathlib import Path

from quest_renamer.infrastructure.app_paths import platform_app_paths


class AppPathTests(unittest.TestCase):
    def test_linux_honors_xdg_locations(self) -> None:
        paths = platform_app_paths(
            system="linux",
            environment={
                "XDG_DATA_HOME": "/var/data/user",
                "XDG_CACHE_HOME": "/var/cache/user",
            },
            home=Path("/home/example"),
        )

        self.assertEqual(paths.data, Path("/var/data/user/quest-apk-renamer"))
        self.assertEqual(paths.cache, Path("/var/cache/user/quest-apk-renamer"))

    def test_linux_has_freedesktop_defaults(self) -> None:
        paths = platform_app_paths(
            system="linux",
            environment={},
            home=Path("/home/example"),
        )

        self.assertEqual(paths.data, Path("/home/example/.local/share/quest-apk-renamer"))
        self.assertEqual(paths.cache, Path("/home/example/.cache/quest-apk-renamer"))

    def test_macos_uses_application_support(self) -> None:
        paths = platform_app_paths(
            system="darwin",
            environment={},
            home=Path("/Users/example"),
        )

        self.assertEqual(
            paths.data,
            Path("/Users/example/Library/Application Support/Quest APK Renamer"),
        )

    def test_windows_honors_local_app_data(self) -> None:
        paths = platform_app_paths(
            system="win32",
            environment={"LOCALAPPDATA": "C:/Users/example/AppData/Local"},
            home=Path("C:/Users/example"),
        )

        self.assertEqual(
            paths.data,
            Path("C:/Users/example/AppData/Local/Quest APK Renamer"),
        )


if __name__ == "__main__":
    unittest.main()
