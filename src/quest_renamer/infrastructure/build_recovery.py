"""Small crash-safe pointer to an app-created staging folder."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BuildRecovery:
    staging: Path
    source: Path
    output: Path


def write_build_recovery(
    record_path: Path,
    *,
    staging: Path,
    source: Path,
    output: Path,
) -> None:
    record_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = record_path.with_suffix(record_path.suffix + ".tmp")
    payload = {
        "application": "Quest APK Renamer",
        "record_version": 1,
        "staging": str(staging.resolve()),
        "source": str(source.resolve()),
        "output": str(output.resolve(strict=False)),
    }
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, record_path)


def read_build_recovery(record_path: Path) -> BuildRecovery | None:
    if not record_path.is_file() or record_path.is_symlink():
        return None
    try:
        payload: Any = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("application") != "Quest APK Renamer":
            return None
        raw_staging = Path(str(payload["staging"])).expanduser()
        if raw_staging.is_symlink():
            return None
        staging = raw_staging.resolve()
        source = Path(str(payload["source"])).resolve(strict=False)
        output = Path(str(payload["output"])).resolve(strict=False)
    except (KeyError, OSError, json.JSONDecodeError):
        return None
    if (
        ".staging-" not in staging.name
        or staging.parent != output.parent
        or not staging.is_dir()
        or staging.is_symlink()
    ):
        if not staging.exists():
            record_path.unlink(missing_ok=True)
        return None
    return BuildRecovery(staging, source, output)


def clear_build_recovery(record_path: Path | None, staging: Path) -> None:
    if record_path is None or not record_path.is_file():
        return
    recovery = read_build_recovery(record_path)
    if recovery is None or recovery.staging == staging.resolve(strict=False):
        record_path.unlink(missing_ok=True)
