"""Efficient read-only APK analysis using a manifest-only Apktool decode."""

from __future__ import annotations

import hashlib
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from pathlib import Path

from quest_renamer.domain.analysis import ApkAnalysis, ArchiveAnalysis, ManifestAnalysis
from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.process_runner import ProcessRunner
from quest_renamer.infrastructure.signer_inspection import (
    inspect_signature_details,
    load_signer_registry,
)
from quest_renamer.infrastructure.toolchain import Toolchain

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID = f"{{{ANDROID_NS}}}"
LEGACY_LOADER_ENTRY = "lib/arm64-v8a/libovrplatformloader.so"
ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str], None]


class ApkAnalysisError(RuntimeError):
    pass


def _attribute(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    return node.get(f"{ANDROID}{name}") or node.get(name) or ""


def parse_decoded_manifest(path: Path) -> ManifestAnalysis:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ApkAnalysisError(f"Decoded Android manifest could not be read: {exc}") from exc
    uses_sdk = root.find("uses-sdk")
    application = root.find("application")
    permissions = sorted(
        {
            value
            for node in (
                *root.findall("uses-permission"),
                *root.findall("uses-permission-sdk-23"),
            )
            if (value := _attribute(node, "name"))
        }
    )
    features = sorted(
        {value for node in root.findall("uses-feature") if (value := _attribute(node, "name"))}
    )
    return ManifestAnalysis(
        package_name=root.get("package", ""),
        version_code=_attribute(root, "versionCode"),
        version_name=_attribute(root, "versionName"),
        app_label=_attribute(application, "label"),
        min_sdk=_attribute(uses_sdk, "minSdkVersion"),
        target_sdk=_attribute(uses_sdk, "targetSdkVersion"),
        permissions=tuple(permissions),
        features=tuple(features),
        debuggable=_attribute(application, "debuggable").lower() == "true",
    )


def inspect_apk_archive(apk: Path) -> ArchiveAnalysis:
    abis: set[str] = set()
    dex_files = 0
    native_libraries = 0
    has_legacy_loader = False
    try:
        with zipfile.ZipFile(apk) as archive:
            for item in archive.infolist():
                name = item.filename
                if name.replace("\\", "/").strip("/") == LEGACY_LOADER_ENTRY:
                    has_legacy_loader = True
                if re.fullmatch(r"classes(?:\d+)?\.dex", name):
                    dex_files += 1
                if match := re.match(r"^lib/([^/]+)/[^/]+\.so$", name):
                    abis.add(match.group(1))
                    native_libraries += 1
    except (OSError, zipfile.BadZipFile) as exc:
        raise ApkAnalysisError(
            f"The selected APK is not a readable ZIP archive: {exc}"
        ) from exc
    return ArchiveAnalysis(
        abis=tuple(sorted(abis)),
        dex_files=dex_files,
        native_libraries=native_libraries,
        has_legacy_loader=has_legacy_loader,
    )


def hash_apk(apk: Path, token: CancellationToken) -> str:
    digest = hashlib.sha256()
    try:
        with apk.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                token.raise_if_cancelled()
                digest.update(chunk)
    except OSError as exc:
        raise ApkAnalysisError(f"The APK could not be hashed: {exc}") from exc
    return digest.hexdigest()


class ApktoolAnalyzer:
    def __init__(
        self,
        toolchain: Toolchain,
        *,
        runner: ProcessRunner | None = None,
        temporary_root: Path | None = None,
        signer_registry: Path | None = None,
    ) -> None:
        self.toolchain = toolchain
        self.runner = runner or ProcessRunner()
        self.temporary_root = temporary_root
        self.signer_registry = signer_registry

    def analyze(
        self,
        apk: Path,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> ApkAnalysis:
        token = token or CancellationToken()
        progress = progress or (lambda _value, _message: None)
        log = log or (lambda _message: None)
        if not self.toolchain.analysis_ready:
            detail = "; ".join(self.toolchain.problems) or "Analysis tools are incomplete."
            raise ApkAnalysisError(detail)
        assert self.toolchain.java is not None
        assert self.toolchain.apktool is not None
        apk = apk.expanduser().resolve()
        if not apk.is_file():
            raise ApkAnalysisError("The selected APK no longer exists.")

        token.raise_if_cancelled()
        progress(0.05, "Reading APK contents")
        archive = inspect_apk_archive(apk)
        progress(0.18, "Calculating APK fingerprint")
        sha256 = hash_apk(apk, token)

        signer_identity = None
        signer_lineage = ""
        if self.toolchain.signer is not None:
            progress(0.25, "Reading signing certificate")
            registry = (
                load_signer_registry(self.signer_registry) if self.signer_registry else ()
            )
            signature = inspect_signature_details(
                apk,
                java=self.toolchain.java,
                signer=self.toolchain.signer,
                registry=registry,
                runner=self.runner,
                token=token,
            )
            signer_identity = signature.identity
            signer_lineage = signature.lineage

        try:
            with tempfile.TemporaryDirectory(
                prefix="quest-renamer-analysis-",
                dir=self.temporary_root,
            ) as temporary:
                decoded = Path(temporary) / "decoded"
                progress(0.3, "Reading Android manifest")
                self.runner.run(
                    (
                        self.toolchain.java,
                        "-jar",
                        self.toolchain.apktool,
                        "d",
                        "-f",
                        "--only-manifest",
                        apk,
                        "-o",
                        decoded,
                    ),
                    token=token,
                    log=log,
                )
                manifest = parse_decoded_manifest(decoded / "AndroidManifest.xml")
        except OSError as exc:
            raise ApkAnalysisError(f"Analysis workspace could not be created: {exc}") from exc

        if not manifest.package_name:
            raise ApkAnalysisError("The APK manifest does not contain a package ID.")
        progress(1.0, "APK analysis complete")
        return ApkAnalysis(
            apk=apk,
            package_name=manifest.package_name,
            version_code=manifest.version_code,
            version_name=manifest.version_name,
            app_label=manifest.app_label,
            min_sdk=manifest.min_sdk,
            target_sdk=manifest.target_sdk,
            permissions=manifest.permissions,
            features=manifest.features,
            abis=archive.abis,
            dex_files=archive.dex_files,
            native_libraries=archive.native_libraries,
            file_size=apk.stat().st_size,
            sha256=sha256,
            debuggable=manifest.debuggable,
            has_legacy_loader=archive.has_legacy_loader,
            signer_identity=signer_identity,
            signer_lineage=signer_lineage,
        )
