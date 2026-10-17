import shutil
from collections.abc import Callable
from typing import Any

from .base_file import BaseFile, file_operation


def build_move_path(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def move_path(
            source: str,
            destination: str,
            overwrite: bool = False,
    ) -> dict[str, Any]:
        """Move or rename a file/directory to the exact destination path.
        overwrite=true permits replacing files only; directories are never merged.
        Both paths need write access. Protected roots and trees containing links are rejected.
        """
        src, dst = base.transfer_paths(source, destination, move=True, overwrite=overwrite)
        base.prepare_parent(dst)
        shutil.move(str(src), str(dst))
        return {"source": str(src), "destination": str(dst), "moved": True}

    return move_path
