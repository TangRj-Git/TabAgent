from collections.abc import Callable
from typing import Any

from .base_file import BaseFile, check_boolean, file_operation


def build_create_directory(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def create_directory(
            path: str,
            parents: bool = True,
            exist_ok: bool = True,
    ) -> dict[str, Any]:
        """Create a directory. parents=true creates permitted missing parents.
        exist_ok=true accepts an existing directory. Link targets are rejected.
        """
        check_boolean(parents, "parents")
        check_boolean(exist_ok, "exist_ok")
        target = base.resolve(path, write=True, allow_link=False, kind="directory")
        existed = target.exists()
        if parents:
            base.prepare_parent(target)
        target.mkdir(exist_ok=exist_ok)
        return {"path": str(target), "created": not existed}

    return create_directory
