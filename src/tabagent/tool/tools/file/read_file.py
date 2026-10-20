import json
from collections.abc import Callable

from tabagent.core.exceptions import ToolArgumentsError
from tabagent.tool.tools.file.base_file import (
    MAX_OUTPUT_CHARS,
    BaseFile,
    parameters_schema,
    positive_integer,
)

PARAMETERS = parameters_schema({
    "path": {
        "type": "string",
        "description": "UTF-8 file path, relative to the fixed workspace or absolute."
    },
    "start_line": {
        "type": "integer",
        "minimum": 1,
        "description": "One-based first line; normally 1."
    },
    "max_lines": {
        "type": "integer",
        "minimum": 1,
        "maximum": 2000,
        "description": "Maximum lines to read; normally 200. The character limit may stop earlier."
    },
    "start_column": {
        "type": "integer",
        "minimum": 1,
        "description": "One-based Unicode character position in start_line; normally 1. To continue, copy next_line and next_column from the previous result."
    },
})


def create_read_file(base: BaseFile) -> Callable[..., str]:
    def read_file(
            path: str,
            start_line: int = 1,
            max_lines: int = 200,
            *,
            start_column: int = 1,
    ) -> str:
        """Read a UTF-8 text file of at most 8 MiB, preserving its line endings.

        Use this to inspect known files; use search_text to locate content.
        Returns a content version for later edits. Output is limited to 50,000
        Unicode characters. Continue with next_line and next_column, including
        when a long line spans multiple reads. Both are null at end of file.
        content_truncated indicates the character limit stopped the requested
        line range. Pagination is not a snapshot; restart if version changes.
        """
        positive_integer(start_line, "start_line", 2**63 - 1)
        positive_integer(max_lines, "max_lines", 2000)
        positive_integer(start_column, "start_column", 2**63 - 1)
        target = base.resolve(path)
        content, version, _ = base.read(target)
        lines = content.splitlines(keepends=True)
        index = start_line - 1
        if start_column != 1 and (
                index >= len(lines) or start_column > len(lines[index])
        ):
            raise ToolArgumentsError("start_column must identify a character in start_line.")
        stop = min(index + max_lines, len(lines))
        column = start_column
        remaining = MAX_OUTPUT_CHARS
        selected: list[str] = []
        end_line = None
        while index < stop and remaining:
            line = lines[index][column - 1:]
            part = line[:remaining]
            selected.append(part)
            remaining -= len(part)
            end_line = index + 1
            if len(part) < len(line):
                column += len(part)
                break
            index += 1
            column = 1
        next_line = index + 1 if index < len(lines) else None
        return json.dumps({
            "path": base.display(target),
            "content": "".join(selected),
            "start_line": start_line,
            "start_column": start_column,
            "end_line": end_line,
            "total_lines": len(lines),
            "next_line": next_line,
            "next_column": column if next_line is not None else None,
            "content_truncated": index < stop,
            "version": version
        }, ensure_ascii=False)

    return read_file
