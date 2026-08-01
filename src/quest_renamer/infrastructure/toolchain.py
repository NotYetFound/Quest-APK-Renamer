"""Pinned Android toolchain discovery and integrity verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolArtifact:
    name: str
    version: str
    file_name: str
    url: str
    sha256: str


@dataclass(frozen=True, slots=True)
class Toolchain:
    java: Path | None
    keytool: Path | None
    apktool: Path | None
    signer: Path | None
    problems: tuple[str, ...] = ()

    @property
    def analysis_ready(self) -> bool:
        return self.java is not None and self.apktool is not None

    @property
    def build_ready(self) -> bool:
        return self.analysis_ready and self.keytool is not None and self.signer is not None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_tool_catalog(path: Path) -> dict[str, ToolArtifact]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Tool catalog must contain an object.")
    artifacts: dict[str, ToolArtifact] = {}
    for name, raw in payload.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            raise ValueError("Tool catalog entries must be named objects.")
        try:
            artifacts[name] = ToolArtifact(
                name=name,
                version=str(raw["version"]),
                file_name=str(raw["file"]),
                url=str(raw["url"]),
                sha256=str(raw["sha256"]).lower(),
            )
        except KeyError as exc:
            raise ValueError(f"Tool catalog entry {name} is incomplete.") from exc
    return artifacts


def _first_file(candidates: list[Path]) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(str(candidate.expanduser()))
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_file():
            return candidate.expanduser().resolve()
    return None


def _java_executables(
    *,
    environment: Mapping[str, str],
    resource_root: Path,
    executable: Path,
) -> tuple[Path | None, Path | None]:
    suffix = ".exe" if sys.platform.startswith("win") else ""
    java_candidates: list[Path] = []
    keytool_candidates: list[Path] = []

    if override := environment.get("QAR_JAVA"):
        java_candidates.append(Path(override))
    if override := environment.get("QAR_KEYTOOL"):
        keytool_candidates.append(Path(override))
    for root in (
        resource_root / "runtime" / "java",
        executable.resolve().parent / "runtime" / "java",
    ):
        java_candidates.append(root / "bin" / f"java{suffix}")
        keytool_candidates.append(root / "bin" / f"keytool{suffix}")
    if java_home := environment.get("JAVA_HOME"):
        root = Path(java_home)
        java_candidates.append(root / "bin" / f"java{suffix}")
        keytool_candidates.append(root / "bin" / f"keytool{suffix}")

    if found := shutil.which(f"java{suffix}"):
        java_candidates.append(Path(found))
    if found := shutil.which(f"keytool{suffix}"):
        keytool_candidates.append(Path(found))
    return _first_file(java_candidates), _first_file(keytool_candidates)


def resolve_toolchain(
    *,
    resource_root: Path,
    executable: Path,
    data_root: Path,
    environment: Mapping[str, str] | None = None,
    verify_hashes: bool = True,
) -> Toolchain:
    environment = environment if environment is not None else os.environ
    catalog = load_tool_catalog(resource_root / "resources" / "toolchain.json")
    java, keytool = _java_executables(
        environment=environment,
        resource_root=resource_root,
        executable=executable,
    )
    tool_roots = []
    if override := environment.get("QAR_TOOLS_DIR"):
        tool_roots.append(Path(override).expanduser())
    tool_roots.extend((resource_root / "tools", data_root / "tools"))

    problems: list[str] = []

    def artifact_path(key: str) -> Path | None:
        artifact = catalog[key]
        saw_invalid = False
        seen: set[str] = set()
        for candidate in (root / artifact.file_name for root in tool_roots):
            normalized = os.path.normcase(str(candidate.expanduser()))
            if normalized in seen:
                continue
            seen.add(normalized)
            if not candidate.is_file():
                continue
            path = candidate.expanduser().resolve()
            if not verify_hashes or sha256_file(path) == artifact.sha256:
                return path
            saw_invalid = True
        if not saw_invalid:
            problems.append(f"{artifact.name} {artifact.version} is missing")
        else:
            problems.append(f"{artifact.name} {artifact.version} failed its integrity check")
        return None

    apktool = artifact_path("apktool")
    signer = artifact_path("uber_apk_signer")
    if java is None:
        problems.append("Java runtime is missing")
    if keytool is None:
        problems.append("Java keytool is missing")
    return Toolchain(
        java=java,
        keytool=keytool,
        apktool=apktool,
        signer=signer,
        problems=tuple(problems),
    )
