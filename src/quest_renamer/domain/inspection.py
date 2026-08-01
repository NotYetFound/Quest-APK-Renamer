"""Typed results produced by the detailed APK Inspector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quest_renamer.domain.signers import SignerIdentity


@dataclass(frozen=True, slots=True)
class FeatureDetail:
    name: str
    required: bool


@dataclass(frozen=True, slots=True)
class CertificateDetail:
    subject: str = ""
    issuer: str = ""
    sha256: str = ""
    sha1: str = ""


@dataclass(frozen=True, slots=True)
class SignatureDetail:
    signed: bool = False
    verified: bool = False
    schemes: tuple[str, ...] = ()
    certificates: tuple[CertificateDetail, ...] = ()
    identity: SignerIdentity | None = None
    error: str = ""
    lineage: str = ""


@dataclass(frozen=True, slots=True)
class ReferenceHit:
    path: str
    occurrences: int
    dotted: int
    slashed: int


@dataclass(frozen=True, slots=True)
class ReferencePreview:
    old_package: str
    technical_occurrences: int = 0
    technical_files: tuple[ReferenceHit, ...] = ()
    preserved_files: tuple[ReferenceHit, ...] = ()
    native_warnings: tuple[ReferenceHit, ...] = ()


@dataclass(frozen=True, slots=True)
class DetailedApkAnalysis:
    apk: Path
    package_name: str
    file_size: int
    version_code: str = ""
    version_name: str = ""
    app_label: str = ""
    compile_sdk: str = ""
    min_sdk: str = ""
    target_sdk: str = ""
    gl_es_version: str = ""
    permissions: tuple[str, ...] = ()
    features: tuple[FeatureDetail, ...] = ()
    components: tuple[tuple[str, int], ...] = ()
    debuggable: bool = False
    extract_native_libs: str = ""
    abis: tuple[str, ...] = ()
    locales: tuple[str, ...] = ()
    dex_files: int = 0
    native_libraries: int = 0
    zip_entries: int = 0
    hashes: tuple[tuple[str, str], ...] = ()
    signature: SignatureDetail = SignatureDetail()
    references: ReferencePreview = ReferencePreview("")

    def to_mapping(self) -> dict[str, Any]:
        identity = self.signature.identity
        return {
            "file_name": self.apk.name,
            "file_path": str(self.apk),
            "file_size": self.file_size,
            "package_name": self.package_name,
            "version_code": self.version_code,
            "version_name": self.version_name,
            "app_label": self.app_label,
            "compile_sdk": self.compile_sdk,
            "min_sdk": self.min_sdk,
            "target_sdk": self.target_sdk,
            "gl_es_version": self.gl_es_version,
            "permissions": list(self.permissions),
            "features": [
                {"name": feature.name, "required": feature.required}
                for feature in self.features
            ],
            "components": dict(self.components),
            "debuggable": self.debuggable,
            "extract_native_libs": self.extract_native_libs or None,
            "abis": list(self.abis),
            "locales": list(self.locales),
            "dex_files": self.dex_files,
            "native_libraries": self.native_libraries,
            "zip_entries": self.zip_entries,
            "hashes": dict(self.hashes),
            "signature": {
                "signed": self.signature.signed,
                "verified": self.signature.verified,
                "schemes": {
                    name: name in self.signature.schemes for name in ("v1", "v2", "v3")
                },
                "certificates": [
                    {
                        "subject": certificate.subject or None,
                        "issuer": certificate.issuer or None,
                        "sha256": certificate.sha256 or None,
                        "sha1": certificate.sha1 or None,
                    }
                    for certificate in self.signature.certificates
                ],
                "identity": (
                    {
                        "id": identity.id,
                        "label": identity.label,
                        "full_name": identity.full_name,
                        "color": identity.color,
                    }
                    if identity
                    else None
                ),
                "error": self.signature.error or None,
                "lineage": self.signature.lineage or None,
            },
            "package_references": {
                "old_package": self.references.old_package,
                "technical_occurrences": self.references.technical_occurrences,
                "technical_files": [
                    _reference_mapping(item) for item in self.references.technical_files
                ],
                "preserved_files": [
                    _reference_mapping(item) for item in self.references.preserved_files
                ],
                "native_or_compiled_warnings": [
                    _reference_mapping(item) for item in self.references.native_warnings
                ],
            },
        }


def _reference_mapping(item: ReferenceHit) -> dict[str, str | int]:
    return {
        "path": item.path,
        "occurrences": item.occurrences,
        "dotted": item.dotted,
        "slashed": item.slashed,
    }
