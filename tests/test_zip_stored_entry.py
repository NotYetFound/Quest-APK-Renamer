import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from expansion_fixtures import CancelOnCheck, CountingToken, build_catalog, write_obb

from quest_renamer.domain.operations import CancellationToken, OperationCancelled
from quest_renamer.infrastructure import zip_stored_entry
from quest_renamer.infrastructure.addressables_catalog import CATALOG_ENTRY
from quest_renamer.infrastructure.zip_stored_entry import (
    ZipStoredEntryError,
    rewrite_stored_entry,
)


class RewriteStoredEntryTests(unittest.TestCase):
    def _archive(self, temporary: str) -> Path:
        path = Path(temporary) / "archive.zip"
        write_obb(path, build_catalog([["com.example.old", "content"]]))
        return path

    def test_entry_grows_and_neighbours_survive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._archive(temporary)
            payload = b"x" * 5000

            delta = rewrite_stored_entry(
                path, CATALOG_ENTRY, payload, token=CancellationToken()
            )

            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read(CATALOG_ENTRY), payload)
                self.assertEqual(archive.read("assets/aa/after.bin"), b"after" * 4096)
            self.assertEqual(delta, 5000 - len(build_catalog([["com.example.old", "content"]])))

    def test_entry_shrinks_and_neighbours_survive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._archive(temporary)

            delta = rewrite_stored_entry(
                path, CATALOG_ENTRY, b"tiny", token=CancellationToken()
            )

            self.assertLess(delta, 0)
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read(CATALOG_ENTRY), b"tiny")
                self.assertEqual(archive.read("assets/aa/after.bin"), b"after" * 4096)

    def test_missing_entry_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._archive(temporary)
            with self.assertRaisesRegex(ZipStoredEntryError, "no nothing.bin"):
                rewrite_stored_entry(
                    path, "nothing.bin", b"x", token=CancellationToken()
                )

    def _checks_in_a_plain_run(self, payload: bytes) -> int:
        with tempfile.TemporaryDirectory() as temporary:
            counter = CountingToken()
            rewrite_stored_entry(
                self._archive(temporary), CATALOG_ENTRY, payload, token=counter
            )
            return counter.calls

    def test_cancellation_during_the_region_shift_stops_the_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._archive(temporary)
            payload = b"x" * 5000
            # The shifted region (the trailing 20 KiB entry) spans many blocks.
            with mock.patch.object(zip_stored_entry, "_COPY_BLOCK", 1024):
                plain = self._checks_in_a_plain_run(payload)
                # Calls outside the loop: one before the rewrite, one before the
                # verification. Cancelling on call 5 can only land in the loop.
                self.assertGreater(plain, 2 + 5)
                token = CancelOnCheck(5)
                with self.assertRaises(OperationCancelled):
                    rewrite_stored_entry(path, CATALOG_ENTRY, payload, token=token)
            self.assertEqual(token.calls, 5)

    def test_cancellation_during_a_shrinking_shift_stops_the_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._archive(temporary)
            payload = b"tiny"
            with mock.patch.object(zip_stored_entry, "_COPY_BLOCK", 1024):
                plain = self._checks_in_a_plain_run(payload)
                self.assertGreater(plain, 2 + 5)
                token = CancelOnCheck(5)
                with self.assertRaises(OperationCancelled):
                    rewrite_stored_entry(path, CATALOG_ENTRY, payload, token=token)
            self.assertEqual(token.calls, 5)

    def test_cancellation_between_the_rewrite_and_the_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._archive(temporary)
            payload = b"x" * 5000
            last = self._checks_in_a_plain_run(payload)
            token = CancelOnCheck(last)
            with (
                mock.patch.object(zip_stored_entry, "_verify_rewritten_entry") as verify,
                self.assertRaises(OperationCancelled),
            ):
                rewrite_stored_entry(path, CATALOG_ENTRY, payload, token=token)
            verify.assert_not_called()
            with zipfile.ZipFile(path) as archive:
                # The in-place rewrite had already completed.
                self.assertEqual(archive.read(CATALOG_ENTRY), payload)


if __name__ == "__main__":
    unittest.main()
