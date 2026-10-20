import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from tabagent.core.exceptions import ToolArgumentsError, ToolError, ToolExecutionError
from tabagent.tool.tools.file.base_file import BaseFile, page, parameters_schema

PARAMETERS = parameters_schema({
    "query": {
        "type": "string",
        "minLength": 1,
        "description": "Non-empty literal text by default, or a Python regular expression when regex=true. Matches cannot span lines."
    },
    "path": {
        "type": "string",
        "description": "File or directory, relative to the fixed workspace or absolute; normally '.'. Explicit files bypass ignore rules."
    },
    "glob": {
        "type": ["string", "null"],
        "description": "Case-sensitive fnmatch filter, or null for all files. Without a slash, match basenames at any depth (e.g. '*.py'); otherwise match root-relative paths. '*' can cross slashes; '**/' is not optional. Backslashes are normalized to '/'."
    },
    "regex": {
        "type": "boolean",
        "description": "Treat query as a regular expression; normally false."
    },
    "case_sensitive": {
        "type": "boolean",
        "description": "Match query case exactly; normally true. This does not affect glob, which is always case-sensitive."
    },
    "context_lines": {
        "type": "integer",
        "minimum": 0,
        "maximum": 5,
        "description": "Lines of context before and after each matching line; normally 2. Each displayed line is capped at 2000 characters."
    },
    "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "description": "Maximum matching lines per page; normally 50. The output size limit may return fewer."
    },
    "cursor": {
        "type": ["string", "null"],
        "description": "Copy next_cursor unchanged with the same search parameters, or use null for the first page. Restart if files change."
    },
    "respect_ignore": {
        "type": "boolean",
        "description": "Apply Git ignore rules to directory searches when Git is available; normally true. Explicit file paths bypass this setting."
    },
    "timeout": {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": 30,
        "description": "Time limit in seconds for one search, including traversal and regular expressions; normally 10. On timeout, narrow path/glob or simplify the query."
    },
})


def _search(
        base: BaseFile,
        query: str,
        path: str,
        glob: str | None,
        regex: bool,
        case_sensitive: bool,
        context_lines: int,
        limit: int,
        cursor: str | None,
        respect_ignore: bool,
) -> dict[str, Any]:
    """在独立进程中遍历和匹配，主进程负责限制整个搜索的耗时。"""
    try:
        pattern = re.compile(
            query if regex else re.escape(query),
            0 if case_sensitive else re.IGNORECASE,
        )
    except (re.error, OverflowError, RecursionError) as exc:
        raise ToolArgumentsError("query contains an invalid or overly complex regular expression.") from exc
    target = base.resolve(path)
    if not target.exists():
        raise ToolArgumentsError(f"Search path does not exist: {path!r}.")
    is_directory = target.is_dir()
    if not is_directory and not target.is_file():
        raise ToolArgumentsError("Search path must be a regular file or directory.")
    skipped: list[dict[str, str]] = []
    root = target if is_directory else target.parent
    candidates = base.walk(root, respect_ignore, skipped) if is_directory else [(target, "file")]
    if glob is not None:
        glob = glob.replace("\\", "/")

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
                match = pattern.search(line)
                if match is None:
                    continue
                before = lines[max(0, index - context_lines):index]
                after = lines[index + 1:index + 1 + context_lines]
                # 预览覆盖首次命中位置，而不是总截取行首。
                start = max(0, min(match.start() - 200, len(line) - 2000))
                end = start + 2000
                yield {
                    "path": base.display(child),
                    "line": index + 1,
                    "column": match.start() + 1,
                    "end_column": match.end() + 1,
                    "text": line[start:end],
                    "text_start_column": start + 1,
                    "match_truncated": match.end() > end,
                    "before": [value[:2000] for value in before],
                    "after": [value[:2000] for value in after],
                    "text_truncated": any(
                        len(value) > 2000 for value in [*before, line, *after]
                    ),
                }

    result = page(matches(), limit, cursor)
    result["matches"] = result.pop("items")
    result["skipped"] = skipped[:100]
    result["skipped_count"] = len(skipped)
    result["incomplete"] = bool(skipped) or result["next_cursor"] is not None
    return result


def _search_worker() -> None:
    """内部子进程入口；固定代码从 stdin 接收 JSON，不执行查询中的代码。"""
    try:
        arguments = json.loads(sys.stdin.buffer.read())
        base = BaseFile(arguments.pop("workspace"))
        result = _search(base, **arguments)
    except ToolError as exc:
        result = {"error": {"type": type(exc).__name__, "message": str(exc)}}
    except Exception:
        result = {"error": {"type": "ToolExecutionError", "message": "The search worker failed."}}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode("utf-8"))


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
            *,
            respect_ignore: bool = True,
            timeout: float = 10.0,
    ) -> str:
        """Search UTF-8 text line by line, returning matching lines and context.

        Use find_paths to search filenames and read_file for full file content.
        Directory searches honor Git ignore rules by default, skip .git, and
        never follow directory symlinks. Files over 8 MiB and non-text files
        are skipped and reported. Each displayed line is capped at 2000
        Unicode characters. The matching line preview surrounds its first
        match; column and text_start_column are one-based, and end_column is
        exclusive. match_truncated indicates an oversized match;
        text_truncated also covers clipped context lines.
        Cursors apply only to unchanged parameters and files. regex uses
        Python syntax. The entire search runs in a separate process with a
        time limit; timeout raises an error rather than reporting no matches.
        """
        if not isinstance(query, str) or not query:
            raise ToolArgumentsError("query must be a non-empty string.")
        if not isinstance(path, str) or not path or "\0" in path:
            raise ToolArgumentsError("path must be a non-empty path without null bytes.")
        if type(regex) is not bool or type(case_sensitive) is not bool:
            raise ToolArgumentsError("regex and case_sensitive must be booleans.")
        if type(context_lines) is not int or not 0 <= context_lines <= 5:
            raise ToolArgumentsError("context_lines must be an integer between 0 and 5.")
        if glob is not None and (not isinstance(glob, str) or not glob):
            raise ToolArgumentsError("glob must be null or a non-empty string.")
        if type(respect_ignore) is not bool:
            raise ToolArgumentsError("respect_ignore must be a boolean.")
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ToolArgumentsError("timeout must be a finite number greater than 0 and at most 30 seconds.")
        # 先校验分页，避免无效参数仍启动工作进程。
        page((), limit, cursor)
        arguments = {
            "workspace": str(base.workspace), "query": query, "path": path,
            "glob": glob, "regex": regex, "case_sensitive": case_sensitive,
            "context_lines": context_lines, "limit": limit, "cursor": cursor,
            "respect_ignore": respect_ignore,
        }
        environment = os.environ.copy()
        # 同时支持可编辑安装与由调用方通过 sys.path 加载的源码目录。
        environment["PYTHONPATH"] = os.pathsep.join(
            entry for entry in sys.path if isinstance(entry, str)
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-B", "-c",
                 "from tabagent.tool.tools.file.search_text import _search_worker; _search_worker()"],
                input=json.dumps(arguments, ensure_ascii=True).encode("utf-8"),
                capture_output=True,
                timeout=float(timeout),
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError(
                f"Search exceeded {timeout:g} seconds and was stopped. "
                "Narrow path or glob, use a literal query, or simplify the regular expression."
            ) from exc
        except OSError as exc:
            raise ToolExecutionError("Cannot start the search worker.") from exc
        if completed.returncode != 0:
            raise ToolExecutionError("The search worker exited unexpectedly.")
        try:
            result = json.loads(completed.stdout)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ToolExecutionError("The search worker returned an invalid result.") from exc
        if "error" in result:
            error = result["error"]
            exception = ToolArgumentsError if error["type"] == "ToolArgumentsError" else ToolExecutionError
            raise exception(error["message"])
        return json.dumps(result, ensure_ascii=False)

    return search_text
