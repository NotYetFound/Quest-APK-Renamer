# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from build_support import tkdnd_data_files


project_dir = Path(SPECPATH).parent
macos_dir = project_dir / "macos"
target_arch = os.environ.get("MACOS_TARGET_ARCH") or None
codesign_identity = os.environ.get("MACOS_CODESIGN_IDENTITY") or None

datas = [
    (str(project_dir / "assets"), "assets"),
    (str(project_dir / "resources"), "resources"),
    (str(project_dir / "tools"), "tools"),
    (str(project_dir / "LICENSE"), "."),
    (str(project_dir / "THIRD_PARTY_NOTICES.md"), "."),
    (str(macos_dir / "runtime" / "java"), "runtime/java"),
    (
        str(macos_dir / "runtime" / "platform-tools"),
        "runtime/platform-tools",
    ),
]
dependency_manifest = macos_dir / "runtime" / "DEPENDENCY-HASHES.txt"
if dependency_manifest.is_file():
    datas.append((str(dependency_manifest), "runtime"))
datas += tkdnd_data_files()

a = Analysis(
    [str(project_dir / "quest_apk_renamer.py")],
    pathex=[str(project_dir), str(project_dir / "vendor")],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinterdnd2"],
    hookspath=[str(project_dir / "build_hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
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
    argv_emulation=True,
    target_arch=target_arch,
    codesign_identity=codesign_identity,
    entitlements_file=str(macos_dir / "entitlements.plist"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Quest APK Renamer",
)

app = BUNDLE(
    coll,
    name="Quest APK Renamer.app",
    icon=str(macos_dir / "runtime" / "quest-apk-renamer.icns"),
    bundle_identifier="io.github.questapkrenamer.app",
    version="1.3.0",
    info_plist={
        "CFBundleDisplayName": "Quest APK Renamer",
        "CFBundleName": "Quest APK Renamer",
        "CFBundleShortVersionString": "1.3.0",
        "CFBundleVersion": "1.3.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Released under the MIT License",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Android Package",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": [
                    "com.android.package-archive",
                ],
                "CFBundleTypeExtensions": ["apk"],
            },
        ],
    },
)
