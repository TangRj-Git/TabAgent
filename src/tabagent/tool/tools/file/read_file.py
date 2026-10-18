import json
from collections.abc import Callable

from tabagent.tool.tools.file.base_file import (
    MAX_OUTPUT_CHARS, BaseFile, parameters_schema, positive_integer,
)

PARAMETERS = parameters_schema({
    "path": {"type": "string"},
    "start_line": {"type": "integer", "minimum": 1, "description": "One-based first line; normally 1."},
    "max_lines": {"type": "integer", "minimum": 1, "maximum": 2000, "description": "Normally 200."},
})


def create_read_file(base: BaseFile) -> Callable[..., str]:
    def read_file(path: str, start_line: int = 1, max_lines: int = 200) -> str:
        """Read a UTF-8 text file of at most 8 MiB, preserving its line endings.

        Returns a content version for later edits. Output is limited to 50,000
        characters; content_truncated reports a cut within the selected lines.
        next_line advances past the last returned line, including a clipped line.
        """
        positive_integer(start_line, "start_line", 2**63 - 1)
        positive_integer(max_lines, "max_lines", 2000)
        target = base.resolve(path)
        content, version, _ = base.read(target)
        lines = content.splitlines(keepends=True)
        selected = []
        size = 0
        truncated = False
        for line in lines[start_line - 1:start_line - 1 + max_lines]:
            available = MAX_OUTPUT_CHARS - size
            if available == 0:
                break
            selected.append(line[:available])
            size += len(selected[-1])
            if len(line) > available:
                truncated = True
                break
        end_line = start_line + len(selected) - 1 if selected else None
        next_line = end_line + 1 if end_line is not None and end_line < len(lines) else None
        return json.dumps({
            "path": base.display(target), "content": "".join(selected),
            "start_line": start_line, "end_line": end_line, "total_lines": len(lines),
            "next_line": next_line, "content_truncated": truncated, "version": version,
        }, ensure_ascii=False)

    return read_file
