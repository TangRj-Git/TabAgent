import fnmatch
import json
import re
from collections.abc import Callable

from tabagent.core.exceptions import ToolArgumentsError, ToolError
from tabagent.tool.tools.file.base_file import BaseFile, page, parameters_schema

PARAMETERS = parameters_schema({
    "query": {"type": "string", "description": "Literal text or a Python regular expression."},
    "path": {"type": "string", "description": "File or directory to search; normally '.'."},
    "glob": {"type": ["string", "null"], "description": "Optional case-sensitive file glob, e.g. '*.py'."},
    "regex": {"type": "boolean", "description": "Treat query as a regular expression; normally false."},
    "case_sensitive": {"type": "boolean", "description": "Normally true."},
    "context_lines": {"type": "integer", "minimum": 0, "maximum": 5},
    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
    "cursor": {"type": ["string", "null"]},
})


def create_search_text(base: BaseFile) -> Callable[..., str]:
    def search_text(
            query: str,
            path: str = ".",
            glob: str | None = None,
            regex: bool = False,
            case_sensitive: bool = True,
            context_lines: int = 2,
            limit: int = 50,
            cursor: str | None = None,
    ) -> str:
        """Search UTF-8 text line by line, returning matching lines and context.

        Directory searches honor Git ignore rules when Git is available and do
        not follow symlinks. Files over 8 MiB and non-text files are skipped and
        reported. Each displayed line is capped at 2,000 characters. Cursors
        apply only to an unchanged query and unchanged files. regex uses Python
        syntax; avoid expensive patterns. Explicit file paths bypass ignore rules.
        """
        if not isinstance(query, str) or not query:
            raise ToolArgumentsError("query must be a non-empty string.")
        if type(regex) is not bool or type(case_sensitive) is not bool:
            raise ToolArgumentsError("regex and case_sensitive must be booleans.")
        if type(context_lines) is not int or not 0 <= context_lines <= 5:
            raise ToolArgumentsError("context_lines must be an integer between 0 and 5.")
        if glob is not None and (not isinstance(glob, str) or not glob):
            raise ToolArgumentsError("glob must be null or a non-empty string.")
        try:
            pattern = re.compile(query if regex else re.escape(query), 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise ToolArgumentsError("query contains an invalid regular expression.") from exc
        target = base.resolve(path)
        if not target.exists():
            raise ToolArgumentsError(f"Search path does not exist: {path!r}.")
        skipped: list[dict[str, str]] = []
        root = target if target.is_dir() else target.parent
        candidates = base.walk(root, True, skipped) if target.is_dir() else [(target, "file")]

        def matches():
            for child, kind in candidates:
                if kind != "file":
                    continue
                relative = child.relative_to(root).as_posix()
                if glob and not fnmatch.fnmatchcase(relative if "/" in glob else child.name, glob):
                    continue
                try:
                    content, _, _ = base.read(child)
                except ToolError as exc:
                    skipped.append({"path": base.display(child), "reason": str(exc)})
                    continue
                lines = content.splitlines()
                for index, line in enumerate(lines):
                    if not pattern.search(line):
                        continue
                    before = lines[max(0, index - context_lines):index]
                    after = lines[index + 1:index + 1 + context_lines]
                    yield {
                        "path": base.display(child), "line": index + 1,
                        "text": line[:2000],
                        "before": [value[:2000] for value in before],
                        "after": [value[:2000] for value in after],
                        "text_truncated": any(len(value) > 2000 for value in [*before, line, *after]),
                    }

        result = page(matches(), limit, cursor)
        result["matches"] = result.pop("items")
        result["skipped"] = skipped[:100]
        result["skipped_count"] = len(skipped)
        result["incomplete"] = bool(skipped) or result["next_cursor"] is not None
        return json.dumps(result, ensure_ascii=False)

    return search_text
