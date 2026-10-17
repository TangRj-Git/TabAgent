from collections.abc import Callable
from typing import Any

from .base_file import BaseFile, file_operation


def build_delete_file(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def delete_file(path: str) -> dict[str, Any]:
        """Delete one existing regular file permanently.
        Directories and link targets are not accepted.
        """
        target = base.regular_file(path, write=True)
        target.unlink()
        return {"path": str(target), "deleted": True}

    return delete_file
