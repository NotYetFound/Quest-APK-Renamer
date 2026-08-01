"""Read-only discovery of Quest bundle folders."""

from __future__ import annotations

import csv
from pathlib import Path

from quest_renamer.domain.models import BundleDraft


class BundleSelectionError(ValueError):
    """A selected folder cannot be represented as one unambiguous bundle."""


def _release_metadata(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return {}
    for index, line in enumerate(lines):
        if line.startswith("Game Name;") and index + 1 < len(lines):
            keys = next(csv.reader([line], delimiter=";"))
            values = next(csv.reader([lines[index + 1]], delimiter=";"))
            return dict(zip(keys, values, strict=False))
    return {}


class LocalBundleInspector:
    """Find the visible APK, OBB, and release manifest without decoding the APK."""

    def inspect_folder(self, folder: Path) -> BundleDraft:
        folder = folder.expanduser().resolve()
        if not folder.is_dir():
            raise BundleSelectionError("That folder no longer exists.")

        apks = tuple(sorted(path for path in folder.glob("*.apk") if path.is_file()))
        if not apks:
            raise BundleSelectionError("No APK was found in the selected folder.")
        if len(apks) > 1:
            names = ", ".join(path.name for path in apks[:3])
            raise BundleSelectionError(
                f"This folder contains multiple APKs ({names}). Choose one game folder."
            )

        return self._bundle_for_apk(folder, apks[0])

    def inspect_apk(self, apk: Path) -> BundleDraft:
        """Select one exact APK while pairing data from its containing folder."""
        apk = apk.expanduser().resolve()
        if not apk.is_file() or apk.suffix.lower() != ".apk":
            raise BundleSelectionError("That APK no longer exists.")
        return self._bundle_for_apk(apk.parent, apk)

    def _bundle_for_apk(self, folder: Path, apk: Path) -> BundleDraft:
        manifest = folder / "release.manifest"
        manifest_path = manifest if manifest.is_file() else None
        metadata = _release_metadata(manifest_path)
        package_name = metadata.get("Package Name", "").strip()

        obbs: list[Path] = []
        if package_name:
            package_obb_dir = folder / package_name
            if package_obb_dir.is_dir():
                obbs.extend(package_obb_dir.glob("*.obb"))
        if not obbs:
            obbs.extend(folder.glob("*.obb"))
            for child in folder.iterdir():
                if child.is_dir():
                    obbs.extend(child.glob("*.obb"))

        return BundleDraft(
            root=folder,
            apk=apk,
            obbs=tuple(sorted(set(path.resolve() for path in obbs))),
            manifest=manifest_path,
            game_name=metadata.get("Game Name", "").strip() or folder.name,
            package_name=package_name,
            version_code=metadata.get("Version Code", "").strip(),
        )
