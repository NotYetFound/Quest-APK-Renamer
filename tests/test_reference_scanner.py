import tempfile
import unittest
from pathlib import Path

from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.reference_scanner import count_file_patterns


class ReferenceScannerTests(unittest.TestCase):
    def test_counts_patterns_split_across_small_read_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "asset.bin"
            path.write_bytes(b"xxcom.example.gameyycom/example/gamezz")

            result = count_file_patterns(
                path,
                (b"com.example.game", b"com/example/game"),
                CancellationToken(),
                max_size=1024,
                chunk_size=7,
            )

            self.assertEqual(result, (1, 1))

    def test_skips_files_over_the_caller_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.bin"
            path.write_bytes(b"com.example.game")

            result = count_file_patterns(
                path,
                (b"com.example.game",),
                CancellationToken(),
                max_size=4,
            )

            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
