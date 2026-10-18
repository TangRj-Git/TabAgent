import json
from collections.abc import Callable

from tabagent.core.exceptions import ToolExecutionError
from tabagent.tool.tools.file.base_file import BaseFile, page, parameters_schema

PARAMETERS = parameters_schema({
    "path": {
        "type": "string",
        "description": "Directory path; use '.' for the workspace."
    },
    "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "description": "Page size; normally 100."
    },
    "cursor": {
        "type": ["string", "null"],
        "description": "Previous next_cursor, or null for the first page."
    },
})


def create_list_directory(base: BaseFile) -> Callable[..., str]:
    def list_directory(path: str = ".", limit: int = 100, cursor: str | None = None) -> str:
        """List immediate directory entries, including hidden entries. Does not recurse.

        Relative paths use the fixed workspace. Pagination is not a snapshot;
        restart from the first page if the directory changes.
        """
        target = base.directory(path)
        try:
            entries = (
                {"name": child.name, "path": base.display(child), "kind": base.kind(child)}
                for child in sorted(target.iterdir(), key=lambda item: item.name)
            )
            result = page(entries, limit, cursor)
        except OSError as exc:
            raise ToolExecutionError(f"Cannot list directory: {path!r}.") from exc
        result["entries"] = result.pop("items")
        result["path"] = base.display(target)
        return json.dumps(result, ensure_ascii=False)

    return list_directory
