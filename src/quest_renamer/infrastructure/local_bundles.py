"""Read-only discovery of Quest bundle folders."""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from quest_renamer.domain.models import BundleDraft
from quest_renamer.domain.obb_names import is_safe_preserved_obb, parse_obb_filename


def _files_with_suffix(folder: Path, suffix: str) -> list[Path]:
    """Direct children with the given extension, matched case-insensitively.

    Windows users regularly ship ``Game.APK``/``.OBB``; ``Path.glob`` is
    case-sensitive on Linux and macOS and would report "no APK found".
    """
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    return sorted(path for path in entries if path.suffix.lower() == suffix)


class BundleSelectionError(ValueError):
    """A selected folder cannot be represented as one unambiguous bundle."""


def _obb_package(path: Path, expected_package: str = "") -> str:
    parsed = parse_obb_filename(path.name, expected_package)
    return parsed.package_name if parsed is not None else ""


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

        apks = tuple(
            sorted(path for path in _files_with_suffix(folder, ".apk") if path.is_file())
        )
        if not apks:
            raise BundleSelectionError("No APK was found in the selected folder.")
        if len(apks) > 1:
            names = ", ".join(path.name for path in apks[:3])
            raise BundleSelectionError(
                f"This folder contains multiple APKs ({names}). Choose one game folder."
            )

        return self._bundle_for_apk(folder, apks[0], exact_apk=False)

    def inspect_apk(self, apk: Path) -> BundleDraft:
        """Select one exact APK while pairing data from its containing folder."""
        apk = apk.expanduser().resolve()
        if not apk.is_file() or apk.suffix.lower() != ".apk":
            raise BundleSelectionError("That APK no longer exists.")
        return self._bundle_for_apk(apk.parent, apk, exact_apk=True)

    def apply_apk_identity(
        self,
        bundle: BundleDraft,
        package_name: str,
    ) -> BundleDraft:
        """Attach only expansion files proven to belong to an analyzed APK."""
        folder = bundle.root.resolve()
        package_dir = folder / package_name
        if package_dir.is_dir():
            package_files = tuple(
                sorted(
                    path.resolve()
                    for path in _files_with_suffix(package_dir, ".obb")
                    if path.is_file()
                )
            )
            unsafe = tuple(
                path.name
                for path in package_files
                if not is_safe_preserved_obb(path.name)
            )
            mismatched = tuple(
                path.name
                for path in package_files
                if (parsed := parse_obb_filename(path.name, package_name)) is not None
                and parsed.package_name.casefold() != package_name.casefold()
            )
            if unsafe or mismatched:
                raise BundleSelectionError(
                    "The analyzed app's OBB folder contains unsupported or mismatched "
                    f"files ({', '.join((*unsafe, *mismatched)[:3])})."
                )

        candidates = {
            path.resolve()
            for path in _files_with_suffix(folder, ".obb")
            if path.is_file()
            and (parsed := parse_obb_filename(path.name, package_name)) is not None
            and parsed.package_name.casefold() == package_name.casefold()
        }
        candidates.update(
            path.resolve()
            for child in folder.iterdir()
            if child.is_dir()
            for path in _files_with_suffix(child, ".obb")
            if path.is_file()
            and (parsed := parse_obb_filename(path.name, package_name)) is not None
            and parsed.package_name.casefold() == package_name.casefold()
        )
        if package_dir.is_dir():
            candidates.update(
                path.resolve()
                for path in _files_with_suffix(package_dir, ".obb")
                if path.is_file() and is_safe_preserved_obb(path.name)
            )
        candidates.update(
            path
            for path in bundle.obbs
            if parse_obb_filename(path.name, package_name) is None
            and is_safe_preserved_obb(path.name)
        )
        return replace(
            bundle,
            obbs=tuple(sorted(candidates)),
            package_name=package_name,
        )

    def _bundle_for_apk(
        self,
        folder: Path,
        apk: Path,
        *,
        exact_apk: bool,
    ) -> BundleDraft:
        manifest = folder / "release.manifest"
        manifest_path = manifest if manifest.is_file() else None
        metadata = _release_metadata(manifest_path)
        package_name = metadata.get("Package Name", "").strip()

        obbs: tuple[Path, ...] = ()
        if package_name:
            package_obb_dir = folder / package_name
            if package_obb_dir.is_dir():
                package_obbs = tuple(
                    sorted(
                        path.resolve()
                        for path in _files_with_suffix(package_obb_dir, ".obb")
                    )
                )
                unsafe = tuple(
                    path.name
                    for path in package_obbs
                    if not is_safe_preserved_obb(path.name)
                )
                mismatched = tuple(
                    path.name
                    for path in package_obbs
                    if (obb_package := _obb_package(path, package_name))
                    and obb_package.casefold() != package_name.casefold()
                )
                if unsafe or mismatched:
                    names = ", ".join((*unsafe, *mismatched)[:3])
                    raise BundleSelectionError(
                        f"The package OBB folder contains unsupported files ({names})."
                    )
                obbs = package_obbs
            else:
                obbs = tuple(
                    sorted(
                        path.resolve()
                        for path in _files_with_suffix(folder, ".obb")
                        if _obb_package(path, package_name).casefold()
                        == package_name.casefold()
                    )
                )
        else:
            apks = tuple(path for path in _files_with_suffix(folder, ".apk") if path.is_file())
            # An exact APK in a mixed download folder has no trustworthy way to
            # identify which neighboring expansion files belong to it.
            if not exact_apk or len(apks) == 1:
                candidates = tuple(
                    sorted(
                        {
                            path.resolve()
                            for path in _files_with_suffix(folder, ".obb")
                            if path.is_file()
                        }
                        | {
                            path.resolve()
                            for child in folder.iterdir()
                            if child.is_dir()
                            for path in _files_with_suffix(child, ".obb")
                            if path.is_file()
                        }
                    )
                )
                unsafe = tuple(
                    path.name
                    for path in candidates
                    if not is_safe_preserved_obb(path.name)
                )
                packages = {_obb_package(path).casefold() for path in candidates}
                packages.discard("")
                if unsafe:
                    names = ", ".join(unsafe[:3])
                    raise BundleSelectionError(
                        f"Expansion files use unsupported names ({names})."
                    )
                if len(packages) > 1:
                    raise BundleSelectionError(
                        "This folder contains OBB files for multiple packages. "
                        "Choose one complete game folder."
                    )
                obbs = candidates

        return BundleDraft(
            root=folder,
            apk=apk,
            obbs=obbs,
            manifest=manifest_path,
            game_name=metadata.get("Game Name", "").strip() or folder.name,
            package_name=package_name,
            version_code=metadata.get("Version Code", "").strip(),
        )
