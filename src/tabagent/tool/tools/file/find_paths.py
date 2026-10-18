import fnmatch
import json
from collections.abc import Callable

from tabagent.core.exceptions import ToolArgumentsError
from tabagent.tool.tools.file.base_file import BaseFile, page, parameters_schema

PARAMETERS = parameters_schema({
    "pattern": {
        "type": "string",
        "description": "Case-sensitive glob matched against names or relative paths, e.g. '*.py'."
    },
    "path": {
        "type": "string",
        "description": "Search root; normally '.'."
    },
    "kind": {
        "type": "string",
        "enum": [
            "file",
            "directory",
            "any"
        ]
    },
    "respect_ignore": {
        "type": "boolean",
        "description": "Apply repository Git ignore rules when Git is available; normally true."
    },
    "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000
    },
    "cursor": {
        "type": ["string", "null"]
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

        Patterns without '/' match names; other patterns match paths relative
        to the search root using fnmatch semantics. Never traverse directory
        symlinks or .git. Git ignore rules apply only inside Git repositories
        when Git is installed. Reuse cursors only with the same query.
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
