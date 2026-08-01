"""Read-only APK analysis results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.signers import SignerIdentity


@dataclass(frozen=True, slots=True)
class ManifestAnalysis:
    package_name: str
    version_code: str = ""
    version_name: str = ""
    app_label: str = ""
    min_sdk: str = ""
    target_sdk: str = ""
    permissions: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    debuggable: bool = False


@dataclass(frozen=True, slots=True)
class ArchiveAnalysis:
    abis: tuple[str, ...] = ()
    dex_files: int = 0
    native_libraries: int = 0
    has_legacy_loader: bool = False


@dataclass(frozen=True, slots=True)
class ApkAnalysis:
    apk: Path
    package_name: str
    version_code: str = ""
    version_name: str = ""
    app_label: str = ""
    min_sdk: str = ""
    target_sdk: str = ""
    permissions: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    abis: tuple[str, ...] = ()
    dex_files: int = 0
    native_libraries: int = 0
    file_size: int = 0
    sha256: str = ""
    debuggable: bool = False
    has_legacy_loader: bool = False
    signer_identity: SignerIdentity | None = None
