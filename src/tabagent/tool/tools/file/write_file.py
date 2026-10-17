from collections.abc import Callable
from typing import Any

from .base_file import BaseFile, file_operation


def build_write_file(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def write_file(
            path: str,
            content: str,
            overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write UTF-8 text and create permitted missing parent directories.
        Existing files require overwrite=true. Link targets are rejected.
        Content must fit the configured text file size limit.
        """
        return base.write_text(path, content, overwrite)

    return write_file
