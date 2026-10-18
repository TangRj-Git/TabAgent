"""文件工具共用的路径、文本、分页和写入逻辑。"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from threading import RLock
from typing import Any

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_CHARS = 50_000


def parameters_schema(properties: dict[str, Any]) -> dict[str, Any]:
    """生成 strict=True 使用的 schema；可选值通过 null 表达。"""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def positive_integer(value: int, name: str, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ToolArgumentsError(f"{name} must be an integer between 1 and {maximum}.")


def page(
        items: Iterable[dict[str, Any]],
        limit: int,
        cursor: str | None,
) -> dict[str, Any]:
    """按稳定排序后的偏移分页；目录变化时应从第一页重新查询。"""
    positive_integer(limit, "limit", 1000)
    if cursor is not None and (
            not isinstance(cursor, str) or not cursor.isascii() or not cursor.isdigit()
            or len(cursor) > 12
    ):
        raise ToolArgumentsError("cursor must be null or a cursor returned by this tool.")
    offset = int(cursor) if cursor is not None else 0
    results: list[dict[str, Any]] = []
    size = 0
    next_cursor = None
    for index, item in enumerate(items):
        if index < offset:
            continue
        item_size = len(json.dumps(item, ensure_ascii=False))
        if len(results) == limit or (results and size + item_size > MAX_OUTPUT_CHARS):
            next_cursor = str(index)
            break
        results.append(item)
        size += item_size
    return {"items": results, "next_cursor": next_cursor}


class BaseFile:
    """固定默认目录，不修改进程 cwd；此对象本身不是文件系统沙箱。"""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise ToolArgumentsError("workspace must be an existing directory.")
        # 同一组工具的写入串行执行；外部程序的写入仍需版本检查。
        self.write_lock = RLock()

    def resolve(self, path: str) -> Path:
        if not isinstance(path, str) or not path or "\0" in path:
            raise ToolArgumentsError("path must be a non-empty path without null bytes.")
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self.workspace / target
        try:
            return target.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolArgumentsError("The path could not be resolved.") from exc

    def display(self, path: Path) -> str:
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError:
            return path.as_posix()

    def directory(self, path: str) -> Path:
        target = self.resolve(path)
        if not target.is_dir():
            raise ToolArgumentsError(f"Directory does not exist: {path!r}.")
        return target

    @staticmethod
    def read(path: Path) -> tuple[str, str, bool]:
        """读取 UTF-8 文本，返回内容、原始字节版本和 BOM 标记。"""
        try:
            if not path.is_file():
                raise ToolArgumentsError("path must refer to an existing regular file.")
            with path.open("rb") as source:
                raw = source.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise ToolExecutionError(f"Cannot read file: {path.name!r}.") from exc
        if len(raw) > MAX_FILE_BYTES:
            raise ToolArgumentsError("The text file exceeds the 8 MiB size limit.")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ToolArgumentsError("The file is not UTF-8 text.") from exc
        if "\0" in content:
            raise ToolArgumentsError("Binary files are not supported by text tools.")
        return content, hashlib.sha256(raw).hexdigest(), raw.startswith(b"\xef\xbb\xbf")

    @staticmethod
    def encode(content: str, bom: bool = False) -> bytes:
        if not isinstance(content, str) or "\0" in content:
            raise ToolArgumentsError("content must be text without null bytes.")
        try:
            raw = content.encode("utf-8-sig" if bom else "utf-8")
        except UnicodeEncodeError as exc:
            raise ToolArgumentsError("content must be valid Unicode text.") from exc
        if len(raw) > MAX_FILE_BYTES:
            raise ToolArgumentsError("The text file exceeds the 8 MiB size limit.")
        return raw

    def check_version(self, path: Path, expected_version: str | None) -> None:
        if expected_version is None:
            return
        if not isinstance(expected_version, str) or not expected_version:
            raise ToolArgumentsError("expected_version must be null or a file version.")
        if not path.exists() or self.read(path)[1] != expected_version:
            raise ToolExecutionError("The file has changed since it was read.")

    @staticmethod
    def replace(path: Path, raw: bytes) -> None:
        """先完整写入同目录临时文件，再替换目标，保留原有权限位。"""
        temporary: str | None = None
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
                temporary = target.name
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        except OSError as exc:
            raise ToolExecutionError(f"Cannot replace file: {path.name!r}.") from exc
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def walk(
            self,
            root: Path,
            respect_ignore: bool,
            skipped: list[dict[str, str]],
    ) -> Iterator[tuple[Path, str]]:
        """递归遍历；不进入符号链接目录，Git 可用时应用仓库忽略规则。"""
        if type(respect_ignore) is not bool:
            raise ToolArgumentsError("respect_ignore must be a boolean.")
        git = shutil.which("git") if respect_ignore else None
        use_git = False
        if git:
            try:
                probe = subprocess.run(
                    [git, "-C", str(root), "rev-parse", "--show-toplevel"],
                    capture_output=True, timeout=10,
                )
                use_git = probe.returncode == 0
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ToolExecutionError("Cannot inspect Git ignore rules.") from exc

        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name)
                ignored: set[str] = set()
                if use_git and children:
                    result = subprocess.run(
                        [git, "-C", str(root), "check-ignore", "--no-index", "-z", "--stdin"],
                        input="".join(f"{child.as_posix()}\0" for child in children).encode("utf-8"),
                        capture_output=True, timeout=10,
                    )
                    if result.returncode not in (0, 1):
                        raise ToolExecutionError("Cannot evaluate Git ignore rules.")
                    ignored = set(result.stdout.decode("utf-8").split("\0"))
                subdirectories = []
                for child in children:
                    if child.name == ".git" or child.as_posix() in ignored:
                        continue
                    kind = self.kind(child)
                    yield child, kind
                    if kind == "directory":
                        subdirectories.append(child)
                pending.extend(reversed(subdirectories))
            except (OSError, subprocess.TimeoutExpired) as exc:
                skipped.append({"path": self.display(directory), "reason": type(exc).__name__})

    @staticmethod
    def kind(path: Path) -> str:
        if path.is_symlink() or path.is_junction():
            return "symlink"
        if path.is_dir():
            return "directory"
        if path.is_file():
            return "file"
        return "other"
