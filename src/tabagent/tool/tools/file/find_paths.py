import fnmatch
import json
from collections.abc import Callable

from tabagent.core.exceptions import ToolArgumentsError
from tabagent.tool.tools.file.base_file import BaseFile, page, parameters_schema

PARAMETERS = parameters_schema({
    "pattern": {
        "type": "string",
        "description": "Case-sensitive fnmatch pattern. Without a slash, match basenames at any depth (e.g. '*.py'); with slashes, match root-relative paths. '*' can cross slashes; '**/' is not an optional directory prefix. Backslashes are normalized to '/'."
    },
    "path": {
        "type": "string",
        "description": "Root directory, relative to the fixed workspace or absolute; normally '.'."
    },
    "kind": {
        "type": "string",
        "enum": [
            "file",
            "directory",
            "any"
        ],
        "description": "Filter by entry type; normally 'any', which also includes symlinks and other entries."
    },
    "respect_ignore": {
        "type": "boolean",
        "description": "Apply repository Git ignore rules when Git is available; normally true."
    },
    "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "description": "Maximum entries per page; normally 100. The output size limit may return fewer."
    },
    "cursor": {
        "type": ["string", "null"],
        "description": "Copy next_cursor unchanged with the same search parameters, or use null for the first page. Restart if entries change."
    },
})


def create_find_paths(base: BaseFile) -> Callable[..., str]:
    def find_paths(
            pattern: str,
            path: str = ".",
            kind: str = "any",
            respect_ignore: bool = True,
            limit: int = 100,
            cursor: str | None = None
    ) -> str:
        """Recursively find files or directories by a case-sensitive glob.

        Use list_directory for immediate entries and search_text for content.
        Patterns without '/' match names; other patterns match paths relative
        to the search root using fnmatch semantics: '*' can cross '/', and
        '**/' does not match zero directories. Backslashes are normalized to '/'.
        During traversal, skip .git entries and do not descend into directory
        symlinks. Git ignore rules apply only inside Git repositories when Git
        is installed. Reuse cursors only with the same query and unchanged files.
        """
        if not isinstance(pattern, str) or not pattern:
            raise ToolArgumentsError("pattern must be a non-empty string.")
        if kind not in ("file", "directory", "any"):
            raise ToolArgumentsError("kind must be 'file', 'directory', or 'any'.")
        root = base.directory(path)
        pattern = pattern.replace("\\", "/")
        skipped: list[dict[str, str]] = []

        def matches():
            for child, entry_kind in base.walk(root, respect_ignore, skipped):
                name = child.relative_to(root).as_posix() if "/" in pattern else child.name
                if (kind == "any" or kind == entry_kind) and fnmatch.fnmatchcase(name, pattern):
                    yield {
                        "path": base.display(child),
                        "kind": entry_kind
                    }

        result = page(matches(), limit, cursor)
        result["matches"] = result.pop("items")
        result["skipped"] = skipped[:100]
        result["skipped_count"] = len(skipped)
        result["incomplete"] = bool(skipped) or result["next_cursor"] is not None
        return json.dumps(result, ensure_ascii=False)

    return find_paths
