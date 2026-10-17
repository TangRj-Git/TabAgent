from collections.abc import Callable
from fnmatch import fnmatchcase
from typing import Any

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError

from .base_file import BaseFile, check_boolean, check_integer, check_text, file_operation


def build_search_text(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def search_text(
            query: str,
            path: str = ".",
            pattern: str = "*",
            case_sensitive: bool = True,
            offset: int = 0,
            limit: int = 50,
    ) -> dict[str, Any]:
        """Search single-line literal text in UTF-8 files recursively.
        pattern is a case-sensitive name/path glob. Links are skipped.
        offset counts matching lines; limit is 1..100. Use next_offset for more.
        skipped_files counts unreadable, binary, non-UTF-8, or oversized files.
        scan_truncated means the directory scan reached its configured limit.
        """
        check_text(query, "query")
        check_text(pattern, "pattern")
        if "\n" in query or "\r" in query:
            raise ToolArgumentsError("query must contain a single line.")
        check_boolean(case_sensitive, "case_sensitive")
        check_integer(offset, "offset", 0)
        check_integer(limit, "limit", 1, 100)
        root = base.directory(path)
        needle = query if case_sensitive else query.casefold()
        matches = []
        skipped_files = 0
        skipped_matches = 0
        more = False
        scan_truncated = False

        for count, (target, kind) in enumerate(base.walk(root), 1):
            if count > base.max_scan_entries:
                scan_truncated = True
                break
            if kind != "file":
                continue
            relative = target.relative_to(root).as_posix()
            if not (fnmatchcase(target.name, pattern) or fnmatchcase(relative, pattern)):
                continue
            try:
                content = base.load_text(target)
            except (OSError, UnicodeError, ToolArgumentsError, ToolExecutionError):
                skipped_files += 1
                continue

            for number, line in enumerate(content.splitlines(), 1):
                haystack = line if case_sensitive else line.casefold()
                if needle not in haystack:
                    continue
                if skipped_matches < offset:
                    skipped_matches += 1
                    continue
                if len(matches) == limit:
                    more = True
                    break
                matches.append({
                    "path": str(target),
                    "line": number,
                    "text": line[:200],
                    "text_truncated": len(line) > 200,
                })
            if more:
                break

        return {
            "path": str(root),
            "matches": matches,
            "next_offset": offset + len(matches) if more else None,
            "skipped_files": skipped_files,
            "scan_truncated": scan_truncated,
        }

    return search_text
