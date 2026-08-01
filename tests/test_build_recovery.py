import tempfile
import unittest
from pathlib import Path

from quest_renamer.infrastructure.build_recovery import (
    clear_build_recovery,
    read_build_recovery,
    write_build_recovery,
)


class BuildRecoveryTests(unittest.TestCase):
    def test_round_trip_accepts_only_a_sibling_staging_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "finished"
            staging = root / ".finished.staging-test"
            source.mkdir()
            staging.mkdir()
            record = root / "data" / "build-recovery.json"

            write_build_recovery(
                record,
                staging=staging,
                source=source,
                output=output,
            )

            recovered = read_build_recovery(record)
            self.assertIsNotNone(recovered)
            assert recovered is not None
            self.assertEqual(recovered.staging, staging.resolve())
            self.assertEqual(recovered.output, output.resolve())

    def test_stale_record_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = root / "build-recovery.json"
            staging = root / ".finished.staging-gone"
            write_build_recovery(
                record,
                staging=staging,
                source=root / "source",
                output=root / "finished",
            )

            self.assertIsNone(read_build_recovery(record))
            self.assertFalse(record.exists())

    def test_clear_does_not_remove_a_record_for_another_staging_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".finished.staging-current"
            staging.mkdir()
            record = root / "build-recovery.json"
            write_build_recovery(
                record,
                staging=staging,
                source=root / "source",
                output=root / "finished",
            )

            clear_build_recovery(record, root / ".finished.staging-other")

            self.assertTrue(record.is_file())


if __name__ == "__main__":
    unittest.main()
