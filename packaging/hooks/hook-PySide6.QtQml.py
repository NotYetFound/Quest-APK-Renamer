"""Collect only the QML modules used by Quest APK Renamer.

PyInstaller's stock QtQml hook intentionally collects every QML module in the
PySide wheel. That includes WebEngine, 3D, multimedia, virtual keyboards, and
other large module families this app never imports. Filtering at hook time also
prevents their native dependencies from entering the bundle.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()

_QML_ROOT = PurePosixPath(pyside6_library_info.qt_rel_dir) / "qml"
_EXACT_MODULES = (
    PurePosixPath("QtCore"),  # Settings (window geometry, last page)
    PurePosixPath("QtQml"),
    PurePosixPath("QtQuick"),
    PurePosixPath("QtQuick/Controls"),
)
_ALLOWED_MODULE_TREES = (
    PurePosixPath("QtQml/Models"),
    PurePosixPath("QtQml/WorkerScript"),
    PurePosixPath("QtQuick/Controls/Basic"),
    PurePosixPath("QtQuick/Controls/impl"),
    PurePosixPath("QtQuick/Layouts"),
    PurePosixPath("QtQuick/Shapes"),
    PurePosixPath("QtQuick/Templates"),
    PurePosixPath("QtQuick/Window"),
)


def _is_selected_qml_item(item: tuple[str, str]) -> bool:
    destination = PurePosixPath(item[1].replace("\\", "/"))
    try:
        module = destination.relative_to(_QML_ROOT)
    except ValueError:
        return True
    return module in _EXACT_MODULES or any(
        module == allowed or allowed in module.parents for allowed in _ALLOWED_MODULE_TREES
    )


binaries += [item for item in qml_binaries if _is_selected_qml_item(item)]
datas += [item for item in qml_datas if _is_selected_qml_item(item)]
