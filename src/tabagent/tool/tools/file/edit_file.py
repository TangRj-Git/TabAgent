import difflib
import hashlib
import json
from collections.abc import Callable
from typing import Any

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError
from tabagent.tool.tools.file.base_file import BaseFile, parameters_schema

PARAMETERS = parameters_schema({
    "path": {
        "type": "string"
    },
    "edits": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "items": parameters_schema({
            "old_text": {
                "type": "string",
                "description": "Non-empty exact text occurring once in the original file."
            },
            "new_text": {
                "type": "string"
            },
        })
    },
    "expected_version": {
        "type": ["string", "null"],
        "description": "Version returned by read_file, or null."
    },
})


def create_edit_file(base: BaseFile) -> Callable[..., str]:
    def edit_file(
            path: str,
            edits: list[dict[str, Any]],
            expected_version: str | None = None
    ) -> str:
        """Apply unique, non-overlapping exact text replacements to a UTF-8 file.

        All edits match the original file and are validated before writing.
        Preserve existing BOM and untouched line endings. Replacement text is
        used verbatim; use the line endings returned by read_file. Version
        checks detect stale content but do not lock out external editors.
        """
        if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
            raise ToolArgumentsError("edits must contain between 1 and 100 replacements.")
        target = base.resolve(path)
        with base.write_lock:
            content, version, bom = base.read(target)
            if expected_version is not None and expected_version != version:
                raise ToolExecutionError("The file has changed since it was read.")
            replacements = []
            for edit in edits:
                if not isinstance(edit, dict) or set(edit) != {"old_text", "new_text"}:
                    raise ToolArgumentsError("Each edit must contain only old_text and new_text.")
                old, new = edit["old_text"], edit["new_text"]
                if not isinstance(old, str) or not old or not isinstance(new, str):
                    raise ToolArgumentsError("old_text must be non-empty text and new_text must be text.")
                start = content.find(old)
                if start < 0:
                    raise ToolExecutionError("old_text was not found in the original file.")
                if content.find(old, start + 1) >= 0:
                    raise ToolExecutionError("old_text is ambiguous. Include more surrounding text.")
                replacements.append((
                    start,
                    start + len(old),
                    new
                ))
            replacements.sort(key=lambda item: item[0])
            for left, right in zip(replacements, replacements[1:]):
                if left[1] > right[0]:
                    raise ToolArgumentsError("Edits must not overlap in the original file.")
            updated = content
            for start, end, new in reversed(replacements):
                updated = updated[:start] + new + updated[end:]
            raw = base.encode(updated, bom)
            # 写入前再次检查，缩小与外部编辑器发生冲突的时间窗口。
            base.check_version(target, version)
            base.replace(target, raw)
        diff = "\n".join(difflib.unified_diff(
            content.splitlines(),
            updated.splitlines(),
            fromfile=base.display(target),
            tofile=base.display(target),
            lineterm=""
        ))
        return json.dumps({
            "path": base.display(target),
            "applied_edits": len(edits),
            "diff": diff[:8000],
            "diff_truncated": len(diff) > 8000,
            "version": hashlib.sha256(raw).hexdigest()
        }, ensure_ascii=False)

    return edit_file
