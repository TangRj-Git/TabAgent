import difflib
import hashlib
import json
from collections.abc import Callable
from typing import Any

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError
from tabagent.tool.tools.file.base_file import BaseFile, parameters_schema

PARAMETERS = parameters_schema({
    "path": {
        "type": "string",
        "description": "Existing UTF-8 file path, relative to the fixed workspace or absolute."
    },
    "edits": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "description": "Exact, non-overlapping replacements, all matched against the original file rather than earlier replacements in this call.",
        "items": parameters_schema({
            "old_text": {
                "type": "string",
                "description": "Non-empty exact text occurring once in the original file."
            },
            "new_text": {
                "type": "string",
                "description": "Verbatim replacement text. Use an empty string to delete the matched text."
            },
        })
    },
    "expected_version": {
        "type": ["string", "null"],
        "description": "Copy the version from read_file or a previous successful write/edit unchanged, or use null to skip the initial version check."
    },
})


def create_edit_file(base: BaseFile) -> Callable[..., str]:
    def edit_file(
            path: str,
            edits: list[dict[str, Any]],
            expected_version: str | None = None
    ) -> str:
        """Apply unique, non-overlapping exact text replacements to a UTF-8 file.

        Use write_file to create a file or replace its entire content. Read
        the current content before editing. All edits match the original file
        and are validated before writing; matching is case-sensitive.
        Preserve existing BOM and untouched line endings. Replacement text is
        used verbatim; use the line endings returned by read_file. Version
        checks detect stale content but do not lock out external editors.
        """
        if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
            raise ToolArgumentsError("edits must contain between 1 and 100 replacements.")
        if expected_version is not None and (
                not isinstance(expected_version, str) or not expected_version
        ):
            raise ToolArgumentsError("expected_version must be null or a file version.")
        target = base.resolve(path)
        with base.write_lock:
            content, version, bom = base.read(target)
            if expected_version is not None and expected_version != version:
                raise ToolExecutionError(
                    "The file has changed since it was read. Read it again, "
                    "review the current content, and retry with its new version."
                )
            replacements = []
            for number, edit in enumerate(edits, start=1):
                if not isinstance(edit, dict) or set(edit) != {"old_text", "new_text"}:
                    raise ToolArgumentsError(f"Edit {number} must contain only old_text and new_text.")
                old, new = edit["old_text"], edit["new_text"]
                if not isinstance(old, str) or not old or not isinstance(new, str):
                    raise ToolArgumentsError(
                        f"Edit {number}: old_text must be non-empty text and new_text must be text."
                    )
                start = content.find(old)
                if start < 0:
                    raise ToolExecutionError(
                        f"Edit {number}: old_text was not found. Read the file again "
                        "and copy the exact text, including whitespace and line endings."
                    )
                second = content.find(old, start + 1)
                if second >= 0:
                    raise ToolExecutionError(
                        f"Edit {number}: old_text matches at least twice "
                        f"(character offsets {start} and {second}, zero-based). "
                        "Include more surrounding text to select one occurrence."
                    )
                replacements.append((
                    start,
                    start + len(old),
                    new,
                    number,
                ))
            replacements.sort(key=lambda item: item[0])
            for left, right in zip(replacements, replacements[1:]):
                if left[1] > right[0]:
                    raise ToolArgumentsError(
                        f"Edits {left[3]} and {right[3]} overlap in the original file. "
                        "Combine them into one replacement or select disjoint text."
                    )
            updated = content
            for start, end, new, _ in reversed(replacements):
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
