from collections.abc import Callable
from fnmatch import fnmatchcase
from typing import Any

from tabagent.core.exceptions import ToolArgumentsError

from .base_file import BaseFile, check_integer, check_text, file_operation


def build_find_paths(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def find_paths(
            pattern: str,
            path: str = ".",
            kind: str = "any",
            offset: int = 0,
            limit: int = 100,
    ) -> dict[str, Any]:
        """Find files/directories recursively by case-sensitive glob, e.g. *.py.
        Match names or workspace-search-relative paths. kind: any, file, directory.
        Links are skipped. offset starts at 0; limit is 1..200.
        If scan_truncated is true, narrow the search directory; the scan is incomplete.
        """
        check_text(pattern, "pattern")
        if kind not in ("any", "file", "directory"):
            raise ToolArgumentsError("kind must be any, file, or directory.")
        check_integer(offset, "offset", 0)
        check_integer(limit, "limit", 1, 200)
        root = base.directory(path)
        matches = []
        skipped = 0
        more = False
        scan_truncated = False
        for count, (target, entry_kind) in enumerate(base.walk(root), 1):
            if count > base.max_scan_entries:
                scan_truncated = True
                break
            relative = target.relative_to(root).as_posix()
            if kind != "any" and kind != entry_kind:
                continue
            if not (fnmatchcase(target.name, pattern) or fnmatchcase(relative, pattern)):
                continue
            if skipped < offset:
                skipped += 1
                continue
            if len(matches) == limit:
                more = True
                break
            matches.append({"path": str(target), "type": entry_kind})
        return {
            "path": str(root),
            "matches": matches,
            "next_offset": offset + len(matches) if more else None,
            "scan_truncated": scan_truncated,
        }

    return find_paths
