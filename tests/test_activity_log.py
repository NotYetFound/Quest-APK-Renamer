import datetime as dt
import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.activity_log import ActivityLog


class ActivityLogTests(unittest.TestCase):
    def test_log_appends_timestamped_lines_and_returns_a_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.log"
            log = ActivityLog(
                path,
                clock=lambda: dt.datetime(2026, 8, 1, 12, 34, 56, tzinfo=dt.UTC),
            )

            line = log.append("Quest connected.")

            self.assertEqual(
                line,
                "[2026-08-01T12:34:56+00:00] [INFO] Quest connected.",
            )
            self.assertEqual(log.tail(), (line,))

    def test_log_rotates_before_it_grows_past_the_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.log"
            log = ActivityLog(path, max_bytes=1)
            first = log.append("First")
            second = log.append("Second")

            previous = path.with_name("activity.log.1")
            self.assertIn(first, previous.read_text(encoding="utf-8"))
            self.assertIn(second, path.read_text(encoding="utf-8"))

    def test_clear_leaves_an_empty_readable_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.log"
            log = ActivityLog(path)
            log.append("Temporary")

            log.clear()

            self.assertEqual(log.tail(), ())

    def test_structured_event_is_human_readable_and_keeps_full_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.log"
            log = ActivityLog(
                path,
                clock=lambda: dt.datetime(2026, 8, 1, 12, 34, 56, tzinfo=dt.UTC),
            )

            lines = log.append_event(
                "BUILD",
                "Build completed and verified",
                (("Package ID", "com.game → com.game.dev"), ("Duration", "14.2 seconds")),
            )

            self.assertEqual(
                lines[0],
                "[2026-08-01T12:34:56+00:00] [BUILD] Build completed and verified",
            )
            self.assertEqual(lines[1], "    Package ID: com.game → com.game.dev")
            self.assertIn("Duration: 14.2 seconds", path.read_text(encoding="utf-8"))

    def test_export_creates_an_exact_atomic_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = ActivityLog(root / "activity.log")
            log.append("Exact diagnostic output")
            destination = root / "exports" / "support.log"

            log.export(destination)

            self.assertEqual(destination.read_bytes(), log.path.read_bytes())
            self.assertFalse(destination.with_suffix(".log.tmp").exists())


if __name__ == "__main__":
    unittest.main()
