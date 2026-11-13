"""Check that a source swap won't discard files outside the build plan."""

import os
import stat
from pathlib import Path

from quest_renamer.domain.models import BuildRequest


def source_replacement_problem(request: BuildRequest) -> str:
    source = request.source
    root = source.root.resolve()
    if source.selected_as_apk:
        return "Select the complete game folder to replace it, not an individual APK."
    if root in {Path(root.anchor), Path.home().resolve()}:
        return "This source folder is too broad to replace safely."
    try:
        extras = source.extra_files
        if not request.copy_obbs and (source.obbs or extras):
            return "Source replacement requires copying the game's OBBs and extra files."
        files = {source.apk, *source.obbs, *extras}
        if source.manifest is not None:
            files.add(source.manifest)  # regenerated in the new bundle
        # Match the resolved root even when the original selection came through
        # a path alias (e.g. /var on macOS or a short temp path on Windows).
        # Do not resolve the filename: traversal must still reject linked entries.
        files = {path.parent.resolve() / path.name for path in files}
        directories = {
            parent
            for path in files
            for parent in path.parents
            if parent != root and parent.is_relative_to(root)
        }
        pending = [root]
        while pending:
            for path in pending.pop().iterdir():
                info = path.lstat()
                linked = stat.S_ISLNK(info.st_mode) or bool(
                    getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                )
                if not linked and path in directories and stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif linked or path not in files or not stat.S_ISREG(info.st_mode):
                    return (
                        f"Source replacement would leave behind {path.relative_to(root)}. "
                        "Build a separate copy instead."
                    )
        if not os.access(root.parent, os.W_OK):
            return "The source folder's parent cannot be written to."
    except (OSError, ValueError) as exc:
        return f"The source folder could not be checked for safe replacement: {exc}"
    return ""
