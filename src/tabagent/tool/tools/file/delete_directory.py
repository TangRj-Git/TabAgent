import shutil
from collections.abc import Callable
from typing import Any

from .base_file import BaseFile, check_boolean, file_operation


def build_delete_directory(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def delete_directory(
            path: str,
            recursive: bool = False,
    ) -> dict[str, Any]:
        """Delete an empty directory, or its contents when recursive=true.
        Protected roots cannot be removed. Trees containing links are rejected.
        Recursive operations must fit the configured scan limit.
        """
        check_boolean(recursive, "recursive")
        target = base.directory(path, write=True)
        base.protect_root(target)
        if recursive:
            base.check_tree(target, write=True)
            shutil.rmtree(target)
        else:
            target.rmdir()
        return {"path": str(target), "deleted": True}

    return delete_directory
