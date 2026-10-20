import hashlib
import json
from collections.abc import Callable

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError
from tabagent.tool.tools.file.base_file import BaseFile, parameters_schema

PARAMETERS = parameters_schema({
    "path": {
        "type": "string",
        "description": "File path, relative to the fixed workspace or absolute. Missing parent directories are created."
    },
    "content": {
        "type": "string",
        "description": "Complete UTF-8 text to write, not a patch or appended fragment. Empty text creates or replaces with an empty file."
    },
    "overwrite": {
        "type": "boolean",
        "description": "Allow replacing an existing file; normally false."
    },
    "expected_version": {
        "type": ["string", "null"],
        "description": "Copy the version from read_file or a previous successful write/edit unchanged, or use null to skip the version check."
    },
})


def create_write_file(base: BaseFile) -> Callable[..., str]:
    def write_file(
            path: str,
            content: str,
            overwrite: bool = False,
            expected_version: str | None = None
    ) -> str:
        """Create a UTF-8 text file, including missing parent directories.

        Use edit_file for targeted replacements in an existing file. This tool
        writes the entire file and does not append. Existing files require
        overwrite=true. expected_version rejects stale writes.
        Content is written exactly as supplied, without newline
        conversion. Maximum size is 8 MiB. Version checks are not external locks.
        """
        if type(overwrite) is not bool:
            raise ToolArgumentsError("overwrite must be a boolean.")
        target = base.resolve(path)
        raw = base.encode(content)
        with base.write_lock:
            exists = target.exists()
            if exists and not target.is_file():
                raise ToolArgumentsError("path must refer to a regular file.")
            if exists and not overwrite:
                raise ToolExecutionError("The file already exists. Set overwrite=true to replace it.")
            base.check_version(target, expected_version)
            try:
                if exists:
                    base.replace(target, raw)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # 排他创建，避免检查之后出现的新文件被覆盖。
                    with target.open("xb") as output:
                        output.write(raw)
            except OSError as exc:
                raise ToolExecutionError(f"Cannot write file: {path!r}.") from exc
        return json.dumps({
            "path": base.display(target),
            "created": not exists,
            "bytes_written": len(raw),
            "version": hashlib.sha256(raw).hexdigest()
        }, ensure_ascii=False)

    return write_file
