import shutil
from collections.abc import Callable
from typing import Any

from .base_file import BaseFile, file_operation


def build_copy_path(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def copy_path(
            source: str,
            destination: str,
            overwrite: bool = False,
    ) -> dict[str, Any]:
        """Copy a file/directory to the exact destination path.
        Source needs read access; destination needs write access.
        overwrite=true replaces files only. Links and directory merging are rejected.
        """
        src, dst = base.transfer_paths(source, destination, move=False, overwrite=overwrite)
        base.prepare_parent(dst)
        if src.is_dir():
            shutil.copytree(src, dst)
        elif overwrite:
            shutil.copy2(src, dst)
        else:
            # 与 write_file 一样，默认独占创建目标文件。
            with src.open("rb") as reader, dst.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            shutil.copystat(src, dst)
        return {"source": str(src), "destination": str(dst), "copied": True}

    return copy_path
