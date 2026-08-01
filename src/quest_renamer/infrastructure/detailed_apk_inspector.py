"""Cancellable full-decode implementation of the detailed APK Inspector."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from quest_renamer.domain.inspection import (
    DetailedApkAnalysis,
    FeatureDetail,
    ReferenceHit,
    ReferencePreview,
    SignatureDetail,
)
from quest_renamer.domain.operations import CancellationToken
from quest_renamer.infrastructure.process_runner import ProcessRunner
from quest_renamer.infrastructure.signer_inspection import (
    inspect_signature_details,
    load_signer_registry,
)
from quest_renamer.infrastructure.toolchain import Toolchain

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID = f"{{{ANDROID_NS}}}"
TECHNICAL_XML_ROOTS = {"res"}
ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str], None]


class DetailedInspectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ManifestDetails:
    package_name: str
    version_code: str
    version_name: str
    app_label: str
    compile_sdk: str
    min_sdk: str
    target_sdk: str
    gl_es_version: str
    permissions: tuple[str, ...]
    features: tuple[FeatureDetail, ...]
    components: tuple[tuple[str, int], ...]
    debuggable: bool
    extract_native_libs: str


@dataclass(frozen=True, slots=True)
class _ArchiveDetails:
    abis: tuple[str, ...]
    locales: tuple[str, ...]
    dex_files: int
    native_libraries: int
    zip_entries: int


def _attribute(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    return node.get(f"{ANDROID}{name}") or node.get(name) or ""


def _string_value(node: ET.Element) -> str:
    return "".join(node.itertext()).strip()


def load_default_strings(decoded: Path) -> dict[str, str]:
    strings: dict[str, str] = {}
    values = decoded / "res" / "values"
    if not values.is_dir():
        return strings
    for path in sorted(values.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        for node in root.findall("string"):
            name = node.get("name")
            if name and name not in strings:
                strings[name] = _string_value(node)
    return strings


def resolve_label(value: str, strings: dict[str, str]) -> str:
    match = re.fullmatch(r"@(?:[^:]+:)?string/([A-Za-z0-9_.]+)", value)
    return strings.get(match.group(1), value) if match else value


def decode_gl_es(value: str) -> str:
    if not value:
        return ""
    try:
        encoded = int(value, 0)
    except ValueError:
        return value
    return f"{encoded >> 16}.{encoded & 0xFFFF}"


def parse_detailed_manifest(path: Path, strings: dict[str, str]) -> _ManifestDetails:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise DetailedInspectionError(
            f"Decoded Android manifest could not be read: {exc}"
        ) from exc
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
    features: list[FeatureDetail] = []
    gl_es = ""
    for node in root.findall("uses-feature"):
        if not gl_es and (value := _attribute(node, "glEsVersion")):
            gl_es = decode_gl_es(value)
        if name := _attribute(node, "name"):
            features.append(FeatureDetail(name, _attribute(node, "required") != "false"))
    component_names = ("activity", "activity-alias", "service", "receiver", "provider")
    components = tuple(
        (name, len(application.findall(name)) if application is not None else 0)
        for name in component_names
    )
    return _ManifestDetails(
        package_name=root.get("package", ""),
        version_code=_attribute(root, "versionCode"),
        version_name=_attribute(root, "versionName"),
        app_label=resolve_label(_attribute(application, "label"), strings),
        compile_sdk=(
            _attribute(root, "compileSdkVersion") or root.get("platformBuildVersionCode", "")
        ),
        min_sdk=_attribute(uses_sdk, "minSdkVersion"),
        target_sdk=_attribute(uses_sdk, "targetSdkVersion"),
        gl_es_version=gl_es,
        permissions=tuple(permissions),
        features=tuple(sorted(features, key=lambda item: item.name.lower())),
        components=components,
        debuggable=_attribute(application, "debuggable").lower() == "true",
        extract_native_libs=_attribute(application, "extractNativeLibs"),
    )


def parse_apktool_metadata(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    def grab(pattern: str) -> str:
        match = re.search(pattern, text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    return {
        "min_sdk": grab(r"^\s*minSdkVersion:\s*['\"]?([^'\"\n]+)"),
        "target_sdk": grab(r"^\s*targetSdkVersion:\s*['\"]?([^'\"\n]+)"),
        "version_code": grab(r"^\s*versionCode:\s*['\"]?([^'\"\n]+)"),
        "version_name": grab(r"^\s*versionName:\s*['\"]?([^'\"\n]+)"),
    }


def inspect_archive(apk: Path) -> _ArchiveDetails:
    abis: set[str] = set()
    locales: set[str] = set()
    dex_files = 0
    native_libraries = 0
    entries = 0
    try:
        with zipfile.ZipFile(apk) as archive:
            for info in archive.infolist():
                name = info.filename
                entries += 1
                if match := re.match(r"^lib/([^/]+)/[^/]+\.so$", name):
                    abis.add(match.group(1))
                    native_libraries += 1
                if re.fullmatch(r"classes(?:\d+)?\.dex", name):
                    dex_files += 1
                if match := re.match(r"^res/values-([^/]+)/", name):
                    qualifier = match.group(1)
                    if re.search(r"(^|-)r[A-Z]{2}($|-)", qualifier) or re.match(
                        r"^[a-z]{2,3}(?:-|$)", qualifier
                    ):
                        locales.add(qualifier)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DetailedInspectionError(f"The APK is not a readable ZIP archive: {exc}") from exc
    return _ArchiveDetails(
        tuple(sorted(abis)),
        tuple(sorted(locales)),
        dex_files,
        native_libraries,
        entries,
    )


def compute_hashes(apk: Path, token: CancellationToken) -> tuple[tuple[str, str], ...]:
    digests = {
        "md5": hashlib.md5(usedforsecurity=False),
        "sha1": hashlib.sha1(usedforsecurity=False),
        "sha256": hashlib.sha256(),
    }
    try:
        with apk.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                token.raise_if_cancelled()
                for digest in digests.values():
                    digest.update(chunk)
    except OSError as exc:
        raise DetailedInspectionError(f"The APK could not be hashed: {exc}") from exc
    return tuple((name, digest.hexdigest()) for name, digest in digests.items())


def _technical_file(relative: Path) -> bool:
    return (
        relative.as_posix() in {"AndroidManifest.xml", "apktool.yml"}
        or relative.suffix.lower() == ".smali"
        or (
            len(relative.parts) > 1
            and relative.parts[0] in TECHNICAL_XML_ROOTS
            and relative.suffix.lower() == ".xml"
        )
    )


def scan_package_references(
    decoded: Path,
    old_package: str,
    token: CancellationToken,
) -> ReferencePreview:
    exact = old_package.encode("utf-8")
    slashed_value = old_package.replace(".", "/")
    slashed = slashed_value.encode("utf-8")
    technical: list[ReferenceHit] = []
    preserved: list[ReferenceHit] = []
    native: list[ReferenceHit] = []
    total = 0
    for path in decoded.rglob("*"):
        token.raise_if_cancelled()
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(decoded)
        try:
            if path.stat().st_size > 64 * 1024 * 1024:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        dotted_count = data.count(exact)
        slashed_count = data.count(slashed) if slashed != exact else 0
        occurrences = dotted_count + slashed_count
        if not occurrences:
            continue
        hit = ReferenceHit(relative.as_posix(), occurrences, dotted_count, slashed_count)
        if _technical_file(relative):
            technical.append(hit)
            total += occurrences
        else:
            preserved.append(hit)
            if relative.suffix.lower() in {".so", ".dex"}:
                native.append(hit)
    return ReferencePreview(
        old_package,
        total,
        tuple(technical),
        tuple(preserved),
        tuple(native),
    )


def write_analysis_report(path: Path, analysis: DetailedApkAnalysis) -> None:
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(analysis.to_mapping(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class FullDecodeApkInspector:
    def __init__(
        self,
        toolchain: Toolchain,
        *,
        signer_registry: Path,
        runner: ProcessRunner | None = None,
        temporary_root: Path | None = None,
    ) -> None:
        self.toolchain = toolchain
        self.signer_registry = signer_registry
        self.runner = runner or ProcessRunner()
        self.temporary_root = temporary_root

    def inspect(
        self,
        apk: Path,
        *,
        token: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> DetailedApkAnalysis:
        token = token or CancellationToken()
        progress = progress or (lambda _value, _message: None)
        log = log or (lambda _message: None)
        if not self.toolchain.analysis_ready:
            raise DetailedInspectionError(
                "; ".join(self.toolchain.problems) or "APK analysis tools are unavailable."
            )
        assert self.toolchain.java is not None
        assert self.toolchain.apktool is not None
        apk = apk.expanduser().resolve()
        if not apk.is_file() or apk.suffix.lower() != ".apk":
            raise DetailedInspectionError("Choose an existing APK file to inspect.")
        if self.temporary_root is not None:
            self.temporary_root.mkdir(parents=True, exist_ok=True)

        progress(0.03, "Reading APK archive")
        archive = inspect_archive(apk)
        progress(0.10, "Calculating file hashes")
        hashes = compute_hashes(apk, token)
        signature = SignatureDetail(error="APK signer tool is unavailable.")
        if self.toolchain.signer is not None:
            progress(0.18, "Inspecting signing certificate")
            signature = inspect_signature_details(
                apk,
                java=self.toolchain.java,
                signer=self.toolchain.signer,
                registry=load_signer_registry(self.signer_registry),
                runner=self.runner,
                token=token,
            )

        try:
            with tempfile.TemporaryDirectory(
                prefix="quest-renamer-inspector-", dir=self.temporary_root
            ) as temporary:
                decoded = Path(temporary) / "decoded"
                progress(0.25, "Decoding APK for inspection")
                self.runner.run(
                    (
                        self.toolchain.java,
                        "-jar",
                        self.toolchain.apktool,
                        "d",
                        "-f",
                        apk,
                        "-o",
                        decoded,
                    ),
                    token=token,
                    log=log,
                )
                progress(0.72, "Reading manifest and resources")
                manifest = parse_detailed_manifest(
                    decoded / "AndroidManifest.xml", load_default_strings(decoded)
                )
                metadata = parse_apktool_metadata(decoded / "apktool.yml")
                if not manifest.package_name:
                    raise DetailedInspectionError(
                        "The decoded manifest does not contain a package ID."
                    )
                progress(0.82, "Previewing package references")
                references = scan_package_references(decoded, manifest.package_name, token)
        except OSError as exc:
            raise DetailedInspectionError(
                f"The inspection workspace could not be created: {exc}"
            ) from exc

        progress(1.0, "Inspection complete")
        return DetailedApkAnalysis(
            apk=apk,
            package_name=manifest.package_name,
            file_size=apk.stat().st_size,
            version_code=manifest.version_code or metadata.get("version_code", ""),
            version_name=manifest.version_name or metadata.get("version_name", ""),
            app_label=manifest.app_label,
            compile_sdk=manifest.compile_sdk,
            min_sdk=manifest.min_sdk or metadata.get("min_sdk", ""),
            target_sdk=manifest.target_sdk or metadata.get("target_sdk", ""),
            gl_es_version=manifest.gl_es_version,
            permissions=manifest.permissions,
            features=manifest.features,
            components=manifest.components,
            debuggable=manifest.debuggable,
            extract_native_libs=manifest.extract_native_libs,
            abis=archive.abis,
            locales=archive.locales,
            dex_files=archive.dex_files,
            native_libraries=archive.native_libraries,
            zip_entries=archive.zip_entries,
            hashes=hashes,
            signature=signature,
            references=references,
        )
