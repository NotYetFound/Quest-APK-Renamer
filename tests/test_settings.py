import json
import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.settings import AppSettings
from quest_renamer.infrastructure.settings_store import JsonSettingsStore


class SettingsTests(unittest.TestCase):
    def test_missing_or_invalid_file_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            store = JsonSettingsStore(path)
            self.assertEqual(store.load(), AppSettings())
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(store.load(), AppSettings())

    def test_settings_are_saved_atomically_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            store = JsonSettingsStore(path)
            settings = AppSettings(copy_obbs=False, check_updates=False)

            store.save(settings)

            self.assertEqual(store.load(), settings)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_unknown_and_wrong_typed_values_do_not_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                json.dumps({"copy_obbs": "no", "check_updates": False, "extra": True}),
                encoding="utf-8",
            )

            settings = JsonSettingsStore(path).load()

            self.assertTrue(settings.copy_obbs)
            self.assertFalse(settings.check_updates)

    def test_setting_updates_are_immutable_and_validated(self) -> None:
        original = AppSettings()
        changed = original.with_value("copy_obbs", False)
        self.assertTrue(original.copy_obbs)
        self.assertFalse(changed.copy_obbs)
        with self.assertRaises(KeyError):
            original.with_value("unknown", True)
        with self.assertRaises(TypeError):
            original.with_value("copy_obbs", "false")

    def test_dismissed_update_is_persisted_as_text(self) -> None:
        settings = AppSettings().with_value("dismissed_update", "v1.0.0")
        self.assertEqual(settings.dismissed_update, "v1.0.0")
        with self.assertRaises(TypeError):
            settings.with_value("dismissed_update", True)


if __name__ == "__main__":
    unittest.main()
