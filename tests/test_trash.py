import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quest_renamer.infrastructure.trash import move_to_trash


class TrashTests(unittest.TestCase):
    def test_qt_trash_success_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "finished"
            folder.mkdir()
            with patch("quest_renamer.infrastructure.trash.QFile") as qfile:
                qfile.moveToTrash.return_value = (True, "/trash/finished")

                move_to_trash(folder)

            qfile.moveToTrash.assert_called_once_with(str(folder.resolve()))

    def test_qt_trash_failure_never_falls_back_to_permanent_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "finished"
            folder.mkdir()
            with patch("quest_renamer.infrastructure.trash.QFile") as qfile:
                qfile.moveToTrash.return_value = (False, "")

                with self.assertRaises(OSError):
                    move_to_trash(folder)

            self.assertTrue(folder.is_dir())


if __name__ == "__main__":
    unittest.main()
