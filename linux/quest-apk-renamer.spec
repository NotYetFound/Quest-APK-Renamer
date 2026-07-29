# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


project_dir = Path(SPECPATH).parent
linux_dir = project_dir / "linux"

datas = [
    (str(project_dir / "assets"), "assets"),
    (str(project_dir / "tools"), "tools"),
    (str(project_dir / "LICENSE"), "."),
    (str(project_dir / "THIRD_PARTY_NOTICES.md"), "."),
    (str(linux_dir / "runtime" / "java"), "runtime/java"),
    (
        str(linux_dir / "runtime" / "platform-tools"),
        "runtime/platform-tools",
    ),
]
dependency_manifest = linux_dir / "runtime" / "DEPENDENCY-HASHES.txt"
if dependency_manifest.is_file():
    datas.append((str(dependency_manifest), "runtime"))
datas += collect_data_files("tkinterdnd2")

a = Analysis(
    [str(project_dir / "quest_apk_renamer.py")],
    pathex=[str(project_dir), str(project_dir / "vendor")],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinterdnd2"],
    hookspath=[],
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Quest APK Renamer",
)
