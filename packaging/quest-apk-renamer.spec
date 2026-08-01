# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.building.datastruct import TOC
from PyInstaller.utils.hooks import collect_data_files


project_dir = Path(SPECPATH).parent
runtime_dir = Path(os.environ["QAR_PACKAGE_RUNTIME"]).resolve()
icon_path = os.environ.get("QAR_PACKAGE_ICON") or None
version_file = os.environ.get("QAR_WINDOWS_VERSION_FILE") or None
target_arch = os.environ.get("MACOS_TARGET_ARCH") or None
codesign_identity = os.environ.get("MACOS_CODESIGN_IDENTITY") or None

datas = collect_data_files("quest_renamer")
for source, destination in (
    (runtime_dir / "java", "quest_renamer/runtime/java"),
    (runtime_dir / "platform-tools", "quest_renamer/runtime/platform-tools"),
    (runtime_dir / "tools", "quest_renamer/tools"),
):
    if source.is_dir():
        datas.append((str(source), destination))
manifest = runtime_dir / "DEPENDENCY-HASHES.txt"
if manifest.is_file():
    datas.append((str(manifest), "quest_renamer/runtime"))
datas.extend(
    (
        (str(project_dir / "LICENSE"), "."),
        (str(project_dir / "THIRD_PARTY_NOTICES.md"), "."),
    )
)

unused_qt_modules = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPositioning",
    "PySide6.QtQuick3D",
    "PySide6.QtRemoteObjects",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

a = Analysis(
    [str(project_dir / "src" / "quest_renamer" / "main.py")],
    pathex=[str(project_dir / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[str(project_dir / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=unused_qt_modules,
    noarchive=False,
)
# Qt's TIFF image plugin is not used by this application. On Linux it can add a
# dependency on a distro-specific libtiff soname, so leave it out of every
# package rather than weakening the otherwise self-contained bundle.
a.binaries = TOC(
    entry
    for entry in a.binaries
    if "/imageformats/libqtiff" not in entry[0].replace("\\", "/")
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Quest APK Renamer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=sys.platform == "darwin",
    target_arch=target_arch if sys.platform == "darwin" else None,
    codesign_identity=codesign_identity if sys.platform == "darwin" else None,
    entitlements_file=(
        str(project_dir / "packaging" / "macos" / "entitlements.plist")
        if sys.platform == "darwin"
        else None
    ),
    icon=icon_path,
    version=version_file if sys.platform.startswith("win") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Quest APK Renamer",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Quest APK Renamer.app",
        icon=icon_path,
        bundle_identifier="io.github.questapkrenamer.app",
        version=os.environ["APP_VERSION"],
        info_plist={
            "CFBundleDisplayName": "Quest APK Renamer",
            "CFBundleName": "Quest APK Renamer",
            "CFBundleShortVersionString": os.environ["APP_VERSION"],
            "CFBundleVersion": os.environ["APP_VERSION"],
            "LSApplicationCategoryType": "public.app-category.developer-tools",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
        },
    )
