import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtWidgets import QFileDialog

from quest_renamer.infrastructure.legacy_file_picker import LegacyPickerResult
from quest_renamer.presentation.file_dialog_controller import (
    FileDialogController,
    existing_dialog_directory,
)


class FakeDialog:
    def __init__(self, result: int, paths: tuple[Path, ...] = ()) -> None:
        self.result = result
        self.paths = paths
        self.options: dict[object, bool] = {}
        self.file_mode: object = None
        self.accept_mode: object = None
        self.name_filters: list[str] = []
        self.default_suffix = ""

    def setWindowTitle(self, _title: str) -> None:
        pass

    def setDirectory(self, _directory: str) -> None:
        pass

    def setOption(self, option: object, enabled: bool) -> None:
        self.options[option] = enabled

    def setFileMode(self, mode: object) -> None:
        self.file_mode = mode

    def setAcceptMode(self, mode: object) -> None:
        self.accept_mode = mode

    def setNameFilters(self, filters: list[str]) -> None:
        self.name_filters = filters

    def setDefaultSuffix(self, suffix: str) -> None:
        self.default_suffix = suffix

    def selectFile(self, _name: str) -> None:
        pass

    def exec(self) -> int:
        return self.result

    def selectedFiles(self) -> list[str]:
        return [str(path) for path in self.paths]


class DialogSequence:
    def __init__(self, *dialogs: FakeDialog) -> None:
        self.dialogs = list(dialogs)
        self.created: list[FakeDialog] = []

    def __call__(self) -> FakeDialog:
        dialog = self.dialogs.pop(0)
        self.created.append(dialog)
        return dialog


class FakeClock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class FileDialogControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_existing_directory_walks_up_from_a_removed_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(
                existing_dialog_directory(str(root / "removed" / "game.apk")),
                root.resolve(),
            )

    def test_native_picker_is_used_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary)
            native = FakeDialog(QFileDialog.DialogCode.Accepted, (selected,))
            sequence = DialogSequence(native)
            controller = FileDialogController(
                dialog_factory=sequence,
                clock=FakeClock(0.0, 1.0),
                platform_name="win32",
            )
            received: list[str] = []
            controller.folderSelected.connect(
                lambda _purpose, url: received.append(url.toLocalFile())
            )

            controller.chooseFolder("game", "Choose", str(selected))

            self.assertEqual(
                received,
                [QUrl.fromLocalFile(str(selected)).toLocalFile()],
            )
            self.assertFalse(native.options[QFileDialog.Option.DontUseNativeDialog])
            self.assertEqual(len(sequence.created), 1)

    def test_immediate_native_failure_falls_back_to_qt_picker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary)
            native = FakeDialog(QFileDialog.DialogCode.Rejected)
            qt = FakeDialog(QFileDialog.DialogCode.Accepted, (selected,))
            sequence = DialogSequence(native, qt)
            controller = FileDialogController(
                dialog_factory=sequence,
                clock=FakeClock(0.0, 0.01, 1.0, 2.0),
                platform_name="win32",
            )
            received: list[str] = []
            controller.folderSelected.connect(
                lambda _purpose, url: received.append(url.toLocalFile())
            )

            controller.chooseFolder("game", "Choose", str(selected))

            self.assertEqual(
                received,
                [QUrl.fromLocalFile(str(selected)).toLocalFile()],
            )
            self.assertFalse(native.options[QFileDialog.Option.DontUseNativeDialog])
            self.assertTrue(qt.options[QFileDialog.Option.DontUseNativeDialog])

    def test_visible_cancel_does_not_open_another_picker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            native = FakeDialog(QFileDialog.DialogCode.Rejected)
            sequence = DialogSequence(native)
            legacy_calls: list[bool] = []
            controller = FileDialogController(
                dialog_factory=sequence,
                clock=FakeClock(0.0, 1.0),
                legacy_picker=lambda *_args: legacy_calls.append(True),
                platform_name="win32",
            )

            controller.chooseFolder("game", "Choose", temporary)

            self.assertEqual(len(sequence.created), 1)
            self.assertEqual(legacy_calls, [])

    def test_two_immediate_qt_failures_use_legacy_picker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary)
            sequence = DialogSequence(
                FakeDialog(QFileDialog.DialogCode.Rejected),
                FakeDialog(QFileDialog.DialogCode.Rejected),
            )
            legacy_calls: list[str] = []

            def legacy(kind: str, _title: str, _start: Path, _suggested: str) -> object:
                legacy_calls.append(kind)
                return LegacyPickerResult(paths=(selected,))

            controller = FileDialogController(
                dialog_factory=sequence,
                clock=FakeClock(0.0, 0.01, 1.0, 1.01),
                legacy_picker=legacy,
                platform_name="win32",
            )
            received: list[str] = []
            controller.fileSelected.connect(
                lambda _purpose, url: received.append(url.toLocalFile())
            )

            controller.chooseApk("inspect", "Choose APK", temporary)

            self.assertEqual(legacy_calls, ["apk"])
            self.assertEqual(
                received,
                [QUrl.fromLocalFile(str(selected)).toLocalFile()],
            )

    def test_linux_desktop_picker_runs_before_any_qt_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary)
            sequence = DialogSequence()
            desktop_calls: list[str] = []

            def desktop(
                kind: str, _title: str, _start: Path, _suggested: str
            ) -> LegacyPickerResult:
                desktop_calls.append(kind)
                return LegacyPickerResult(paths=(selected,))

            controller = FileDialogController(
                dialog_factory=sequence,
                desktop_picker=desktop,
                platform_name="linux",
            )
            received: list[str] = []
            controller.folderSelected.connect(
                lambda _purpose, url: received.append(url.toLocalFile())
            )

            controller.chooseFolder("game", "Choose", str(selected))

            self.assertEqual(desktop_calls, ["folder"])
            self.assertEqual(sequence.created, [])
            self.assertEqual(
                received,
                [QUrl.fromLocalFile(str(selected)).toLocalFile()],
            )

    def test_linux_desktop_failure_falls_back_to_qt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary)
            qt = FakeDialog(QFileDialog.DialogCode.Accepted, (selected,))
            sequence = DialogSequence(qt)
            controller = FileDialogController(
                dialog_factory=sequence,
                desktop_picker=lambda *_args: LegacyPickerResult(
                    errors=("kdialog unavailable",)
                ),
                clock=FakeClock(0.0, 1.0),
                platform_name="linux",
            )
            received: list[str] = []
            controller.folderSelected.connect(
                lambda _purpose, url: received.append(url.toLocalFile())
            )

            controller.chooseFolder("game", "Choose", str(selected))

            self.assertEqual(len(sequence.created), 1)
            self.assertEqual(
                received,
                [QUrl.fromLocalFile(str(selected)).toLocalFile()],
            )

    def test_library_archive_uses_native_open_and_save_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "library.qarlib"
            open_dialog = FakeDialog(QFileDialog.DialogCode.Accepted, (archive,))
            save_dialog = FakeDialog(QFileDialog.DialogCode.Accepted, (archive,))
            sequence = DialogSequence(open_dialog, save_dialog)
            controller = FileDialogController(
                dialog_factory=sequence,
                clock=FakeClock(0.0, 1.0, 2.0, 3.0),
                platform_name="win32",
            )
            opened: list[str] = []
            saved: list[str] = []
            controller.fileSelected.connect(
                lambda _purpose, url: opened.append(url.toLocalFile())
            )
            controller.saveSelected.connect(
                lambda _purpose, url: saved.append(url.toLocalFile())
            )

            controller.chooseLibraryArchive("import", "Import", str(root))
            controller.saveLibraryArchive("export", "Export", archive.name, str(root))

            self.assertEqual([Path(value) for value in opened], [archive])
            self.assertEqual([Path(value) for value in saved], [archive])
            self.assertIn("*.qarlib", open_dialog.name_filters[0])
            self.assertIn("*.qarlib", save_dialog.name_filters[0])
            self.assertEqual(save_dialog.default_suffix, "qarlib")


if __name__ == "__main__":
    unittest.main()
