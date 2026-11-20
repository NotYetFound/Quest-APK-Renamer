import json
import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.settings import AppSettings
from quest_renamer.infrastructure.settings_store import JsonSettingsStore


class SettingsTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            store = JsonSettingsStore(path)
            self.assertEqual(store.load(), AppSettings())

    def test_invalid_settings_are_preserved_before_defaults_are_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "settings.json"
            store = JsonSettingsStore(path)
            path.write_text("not json", encoding="utf-8")

            self.assertEqual(store.load(), AppSettings())
            self.assertFalse(path.exists())
            self.assertIsNotNone(store.recovery_path)
            assert store.recovery_path is not None
            self.assertEqual(store.recovery_path.read_text(encoding="utf-8"), "not json")
            self.assertIn("preserved", store.warning)

            store.save(AppSettings(check_updates=False))

            self.assertFalse(store.load().check_updates)
            self.assertEqual(store.recovery_path, None)

    def test_settings_are_saved_atomically_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            store = JsonSettingsStore(path)
            settings = AppSettings(copy_obbs=False, check_updates=False)

            store.save(settings)

            self.assertEqual(store.load(), settings)
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            self.assertTrue(path.with_suffix(".json.bak").is_file())

    def test_last_good_settings_are_restored_after_primary_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            store = JsonSettingsStore(path)
            expected = AppSettings(copy_obbs=False, check_updates=False)
            store.save(expected)
            path.write_text("{truncated", encoding="utf-8")

            loaded = store.load()

            self.assertEqual(loaded, expected)
            self.assertIn("last good backup", store.warning)
            assert store.recovery_path is not None
            self.assertEqual(store.recovery_path.read_text(encoding="utf-8"), "{truncated")

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


class DefaultTagTests(unittest.TestCase):
    @staticmethod
    def _old_version_payload(default_tag: str) -> dict[str, object]:
        payload = AppSettings().to_mapping()
        payload.pop("default_tag_mr_migrated", None)
        payload["default_tag"] = default_tag
        return payload

    def test_fresh_settings_default_to_the_mr_tag(self) -> None:
        from quest_renamer.domain.package_ids import with_tag

        self.assertEqual(AppSettings().default_tag, "mr")
        self.assertEqual(with_tag("com.example.game"), "com.mr.example.game")

    def test_old_saved_dev_default_is_migrated_to_mr(self) -> None:
        settings = AppSettings.from_mapping(self._old_version_payload("dev"))
        self.assertEqual(settings.default_tag, "mr")

    def test_old_saved_custom_tag_is_kept(self) -> None:
        settings = AppSettings.from_mapping(self._old_version_payload("test"))
        self.assertEqual(settings.default_tag, "test")

    def test_deliberate_dev_choice_survives_a_round_trip(self) -> None:
        chosen = AppSettings().with_value("default_tag", "dev")
        settings = AppSettings.from_mapping(chosen.to_mapping())
        self.assertEqual(settings.default_tag, "dev")

    def test_store_migrates_an_old_file_once_and_keeps_a_later_dev_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(json.dumps(self._old_version_payload("dev")), encoding="utf-8")
            store = JsonSettingsStore(path)

            migrated = store.load()
            self.assertEqual(migrated.default_tag, "mr")

            store.save(migrated.with_value("default_tag", "dev"))
            self.assertEqual(JsonSettingsStore(path).load().default_tag, "dev")


class DisplayNameGateTests(unittest.TestCase):
    def test_display_name_feature_is_off_by_default(self) -> None:
        from quest_renamer.domain.settings import AppSettings

        settings = AppSettings()
        self.assertFalse(settings.change_display_name)
        self.assertEqual(settings.label_suffix, "")
        self.assertFalse(settings.rename_java_packages)


if __name__ == "__main__":
    unittest.main()
