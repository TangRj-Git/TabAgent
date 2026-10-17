from collections.abc import Callable
from typing import Any

from tabagent.core.exceptions import ToolExecutionError

from .base_file import BaseFile, check_integer, file_operation


def build_read_file(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def read_file(
            path: str,
            start_line: int = 1,
            max_lines: int = 200,
    ) -> dict[str, Any]:
        """Read UTF-8 text with original line endings. start_line begins at 1.
        max_lines is 1..500. Use next_line for the next portion.
        Files and individual lines must fit the configured size limits.
        """
        check_integer(start_line, "start_line")
        check_integer(max_lines, "max_lines", 1, 500)
        target = base.regular_file(path)
        lines = base.load_text(target).splitlines(keepends=True)
        selected = []
        size = 0
        for line in lines[start_line - 1:start_line - 1 + max_lines]:
            if size + len(line) > base.max_read_chars:
                if not selected:
                    raise ToolExecutionError("Requested line exceeds the read character limit.")
                break
            selected.append(line)
            size += len(line)
        end = start_line + len(selected) - 1
        return {
            "path": str(target),
            "start_line": start_line,
            "end_line": end if selected else None,
            "total_lines": len(lines),
            "content": "".join(selected),
            "next_line": end + 1 if selected and end < len(lines) else None,
        }

    return read_file
