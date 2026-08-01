import json
import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.managed_outputs import (
    ManagedOutputError,
    inspect_managed_output,
)


class ManagedOutputTests(unittest.TestCase):
    def _output(self, root: Path) -> Path:
        output = root / "Game — Development"
        output.mkdir()
        (output / "com.example.game.dev.apk").write_bytes(b"apk")
        (output / "quest-renamer-report.json").write_text(
            json.dumps(
                {
                    "application": {"name": "Quest APK Renamer", "version": "1.4.0"},
                    "packages": {
                        "source": "com.example.game",
                        "output": "com.example.game.dev",
                    },
                    "apk": {"name": "com.example.game.dev.apk"},
                }
            ),
            encoding="utf-8",
        )
        return output

    def test_accepts_only_a_complete_app_created_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = self._output(Path(temporary))

            result = inspect_managed_output(output)

            self.assertEqual(result.package_name, "com.example.game.dev")
            self.assertEqual(result.apk_name, "com.example.game.dev.apk")
            self.assertEqual(result.file_count, 2)
            self.assertGreater(result.total_size, 3)

    def test_rejects_a_folder_without_the_app_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "random"
            output.mkdir()
            with self.assertRaisesRegex(ManagedOutputError, "build report"):
                inspect_managed_output(output)

    def test_rejects_report_that_names_a_missing_apk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = self._output(Path(temporary))
            (output / "com.example.game.dev.apk").unlink()
            with self.assertRaisesRegex(ManagedOutputError, "APK"):
                inspect_managed_output(output)


if __name__ == "__main__":
    unittest.main()
