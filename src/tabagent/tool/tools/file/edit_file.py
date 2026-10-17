from collections.abc import Callable
from typing import Any

from tabagent.core.exceptions import ToolArgumentsError

from .base_file import BaseFile, check_text, file_operation


def build_edit_file(base: BaseFile) -> Callable[..., dict[str, Any]]:
    @file_operation
    def edit_file(
            path: str,
            old_text: str,
            new_text: str,
    ) -> dict[str, Any]:
        """Replace one exact occurrence in a UTF-8 file.
        old_text must be non-empty and match exactly once, including overlaps.
        An empty new_text removes the matched fragment. Link targets are rejected.
        """
        check_text(old_text, "old_text")
        check_text(new_text, "new_text", allow_empty=True)
        target = base.regular_file(path, write=True)
        content = base.load_text(target)
        position = content.find(old_text)
        if position < 0:
            raise ToolArgumentsError("old_text was not found in the file.")
        if content.find(old_text, position + 1) >= 0:
            raise ToolArgumentsError("old_text matches more than once. Use a unique fragment.")
        result = base.write_text(
            str(target), content.replace(old_text, new_text, 1), overwrite=True,
        )
        return {**result, "replacements": 1}

    return edit_file
