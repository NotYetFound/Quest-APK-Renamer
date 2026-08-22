#!/usr/bin/env python3
"""Read one artifact from the committed release-runtime lock file."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: read_runtime_lock.py LOCK COMPONENT PLATFORM", file=sys.stderr)
        return 2
    lock_path, component, platform = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        artifact = raw[component][platform]
        url = artifact["url"]
        sha256 = artifact["sha256"]
        version = artifact["version"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"Invalid runtime lock entry {component}/{platform}: {exc}", file=sys.stderr)
        return 1
    if not all(isinstance(value, str) and value for value in (url, sha256, version)):
        print(f"Invalid runtime lock entry {component}/{platform}.", file=sys.stderr)
        return 1
    if not url.startswith("https://") or len(sha256) != 64:
        print(f"Unsafe runtime lock entry {component}/{platform}.", file=sys.stderr)
        return 1
    print(f"{url}\t{sha256.lower()}\t{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
