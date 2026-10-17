from collections.abc import Callable
from typing import Any

from .base_file import BaseFile, check_integer, file_operation


def build_list_directory(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def list_directory(
            path: str = ".",
            offset: int = 0,
            limit: int = 200,
    ) -> dict[str, Any]:
        """List immediate children, sorted by name. offset starts at 0.
        limit is 1..500. Use next_offset to read another page.
        Relative paths are based on the configured workspace.
        """
        check_integer(offset, "offset", 0)
        check_integer(limit, "limit", 1, 500)
        root = base.directory(path)
        children = sorted(root.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        entries = []
        for target in children[offset:offset + limit]:
            if base.is_link(target):
                kind = "link"
            elif target.is_dir():
                kind = "directory"
            elif target.is_file():
                kind = "file"
            else:
                kind = "other"
            entries.append({"name": target.name, "path": str(target), "type": kind})
        end = offset + len(entries)
        return {
            "path": str(root),
            "entries": entries,
            "total_entries": len(children),
            "next_offset": end if end < len(children) else None,
        }

    return list_directory
