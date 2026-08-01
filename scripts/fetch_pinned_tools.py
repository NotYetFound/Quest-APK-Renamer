"""Download the app's checksum-pinned Android components for a release runtime."""

from __future__ import annotations

import argparse
from pathlib import Path

from quest_renamer.infrastructure.tool_manager import PinnedToolManager


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    project = args.project.resolve()
    runtime = args.runtime.resolve()
    manager = PinnedToolManager(
        catalog_path=project / "src/quest_renamer/resources/toolchain.json",
        resource_root=runtime / "empty-resource-root",
        data_root=runtime,
    )
    result = manager.repair_all(log=print)
    if not result.snapshot.all_ready:
        raise SystemExit("Pinned Android components did not verify.")
    for state in result.snapshot.tools:
        print(f"{state.label} {state.version}: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
