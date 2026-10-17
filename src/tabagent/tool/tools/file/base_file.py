import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError


def file_operation(func: Callable[..., Any]) -> Callable[..., Any]:
    """统一转换系统异常，保留签名供 ToolRegistry 自动生成参数定义。"""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as exc:
            raise ToolExecutionError("The requested path does not exist.") from exc
        except FileExistsError as exc:
            raise ToolExecutionError("The destination already exists.") from exc
        except PermissionError as exc:
            raise ToolExecutionError("The operating system denied access.") from exc
        except UnicodeError as exc:
            raise ToolExecutionError("The operation requires valid UTF-8 text.") from exc
        except OSError as exc:
            raise ToolExecutionError(
                f"{func.__name__} failed ({type(exc).__name__})."
            ) from exc

    return wrapper


def check_text(value: str, name: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value):
        requirement = "a string" if allow_empty else "a non-empty string"
        raise ToolArgumentsError(f"{name} must be {requirement}.")


def check_integer(
        value: int,
        name: str,
        minimum: int = 1,
        maximum: int | None = None,
) -> None:
    if type(value) is not int or value < minimum:
        raise ToolArgumentsError(f"{name} must be an integer >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ToolArgumentsError(f"{name} must not exceed {maximum}.")


def check_boolean(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise ToolArgumentsError(f"{name} must be a boolean.")


class BaseFile:
    """
    一次 Agent 运行内共享的文件访问上下文。

    每次运行创建独立实例，workspace 始终指向默认项目目录。
    应用根据用户请求添加临时文件或目录范围；使用 with 或 finally 关闭。
    close() 拒绝后续调用，不回滚文件变更，也不强制中断已经开始的操作。
    这些是应用层路径检查，不提供操作系统沙箱或并发文件系统隔离。
    """

    @file_operation
    def __init__(
            self,
            workspace: str,
            *,
            max_file_bytes: int = 2 * 1024 * 1024,
            max_scan_entries: int = 10000,
            max_read_chars: int = 20000,
    ) -> None:
        check_integer(max_file_bytes, "max_file_bytes")
        check_integer(max_scan_entries, "max_scan_entries")
        check_integer(max_read_chars, "max_read_chars")

        self._closed = False
        self._workspace = Path.cwd()
        self._workspace = self._canonical(workspace)
        if not self._workspace.is_dir():
            raise ToolArgumentsError("Workspace must be an existing directory.")

        self._read_roots: tuple[Path, ...] = (self._workspace,)
        self._write_roots: tuple[Path, ...] = (self._workspace,)
        self._read_files: set[Path] = set()
        self._write_files: set[Path] = set()
        self._removable_roots: set[Path] = set()
        self.max_file_bytes = max_file_bytes
        self.max_scan_entries = max_scan_entries
        self.max_read_chars = max_read_chars

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def closed(self) -> bool:
        return self._closed

    def ensure_open(self) -> None:
        if self._closed:
            raise ToolExecutionError("File access context is closed.")

    def close(self) -> None:
        """结束本次访问范围；可重复调用，关闭后不能重新启用。"""
        self._closed = True
        self._read_roots = ()
        self._write_roots = ()
        self._read_files.clear()
        self._write_files.clear()
        self._removable_roots.clear()

    def __enter__(self) -> Self:
        self.ensure_open()
        return self

    def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def _input_path(self, path: str) -> Path:
        self.ensure_open()
        check_text(path, "path")
        if "\x00" in path:
            raise ToolArgumentsError("Path must not contain NUL characters.")
        target = Path(path).expanduser()
        if os.name == "nt" and target.drive and not target.is_absolute():
            raise ToolArgumentsError("Drive-relative paths are unsupported. Use an absolute path.")
        if not target.is_absolute():
            target = self._workspace / target
        # 不将 Windows 设备名或备用数据流当作普通文件处理。
        if os.name == "nt" and any(
                ":" in part or Path(part).is_reserved()
                for part in target.parts[1:]
        ):
            raise ToolArgumentsError("Reserved paths and alternate data streams are unsupported.")
        return target

    def _canonical(self, path: str) -> Path:
        try:
            return self._input_path(path).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolArgumentsError("Cannot resolve the requested path.") from exc

    @staticmethod
    def is_link(path: Path) -> bool:
        return path.is_symlink() or path.is_junction()

    def resolve(
            self,
            path: str,
            *,
            write: bool = False,
            allow_link: bool = True,
            kind: Literal["file", "directory"] | None = None,
    ) -> Path:
        target = self._canonical(path)
        roots = self._write_roots if write else self._read_roots
        files = self._write_files if write else self._read_files
        directory_access = any(target.is_relative_to(root) for root in roots)
        file_access = target in files and kind != "directory" and not target.is_dir()
        if not directory_access and not file_access:
            action = "Write" if write else "Read"
            raise ToolArgumentsError(
                f"{action} access denied: path is outside permitted paths."
            )
        # 即使目标尚未创建，也不能把文件授权当成目录授权，或反过来。
        if target in self._read_roots and (
                kind == "file" or (target.exists() and not target.is_dir())
        ):
            raise ToolArgumentsError("A directory access root cannot be used as a file.")
        if not allow_link and self.is_link(self._input_path(path)):
            raise ToolArgumentsError("This operation does not accept a link as its target.")
        return target

    def directory(self, path: str, *, write: bool = False) -> Path:
        target = self.resolve(path, write=write, allow_link=not write, kind="directory")
        if not target.is_dir():
            raise ToolArgumentsError("Path must be an existing directory.")
        return target

    def regular_file(self, path: str, *, write: bool = False) -> Path:
        target = self.resolve(path, write=write, allow_link=not write, kind="file")
        if not target.is_file():
            raise ToolArgumentsError("Path must be an existing regular file.")
        return target

    @file_operation
    def grant_file(self, path: str, *, writable: bool = False) -> None:
        """
        临时允许访问单个文件，也可指定尚未创建的文件。

        不开放父目录、兄弟文件或子路径；写权限同时包含读取权限。
        仅由应用根据用户请求调用，不注册给模型。
        """
        check_boolean(writable, "writable")
        target = self._canonical(path)
        if target in self._read_roots or (target.exists() and not target.is_file()):
            raise ToolArgumentsError("File access requires a regular file or a new file path.")
        self._read_files.add(target)
        if writable:
            self._write_files.add(target)

    @file_operation
    def grant_directory(
            self,
            path: str,
            *,
            writable: bool = False,
            allow_remove: bool = False,
    ) -> None:
        """
        临时允许访问目录及其子路径，也可指定尚未创建的目录。

        allow_remove=True 允许删除或移动该目录本身，需要 writable=True。
        默认项目根及其祖先始终受保护；权限仅在本实例中累加，close 后失效。
        仅由应用根据用户请求调用，不注册给模型。
        """
        check_boolean(writable, "writable")
        check_boolean(allow_remove, "allow_remove")
        if allow_remove and not writable:
            raise ToolArgumentsError("allow_remove=True requires writable=True.")
        target = self._canonical(path)
        if target in self._read_files or (target.exists() and not target.is_dir()):
            raise ToolArgumentsError("Directory access requires a directory or a new directory path.")
        if target not in self._read_roots:
            self._read_roots += (target,)
        if writable and target not in self._write_roots:
            self._write_roots += (target,)
        if allow_remove:
            self._removable_roots.add(target)

    def protect_root(self, target: Path) -> None:
        """始终保护默认项目；额外目录根只有明确允许时才能删除或移动。"""
        self.ensure_open()
        if self._workspace.is_relative_to(target) or any(
                root.is_relative_to(target) and root not in self._removable_roots
                for root in self._read_roots
        ):
            raise ToolArgumentsError("Cannot remove or move a protected root directory.")

    def prepare_parent(self, target: Path) -> None:
        """先检查全部缺失父目录，再创建；单个文件授权不会开放父目录。"""
        self.ensure_open()
        missing: list[Path] = []
        parent = target.parent
        while not parent.exists():
            self.resolve(str(parent), write=True, allow_link=False, kind="directory")
            missing.append(parent)
            parent = parent.parent
        if not parent.is_dir():
            raise ToolArgumentsError("Parent path must be a directory.")
        for directory in reversed(missing):
            self.resolve(str(directory), write=True, allow_link=False, kind="directory")
            directory.mkdir(exist_ok=True)

    def load_text(self, target: Path) -> str:
        target = self.regular_file(str(target))
        with target.open("rb") as stream:
            data = stream.read(self.max_file_bytes + 1)
        if len(data) > self.max_file_bytes:
            raise ToolExecutionError("File exceeds the configured text file size limit.")
        if b"\x00" in data:
            raise ToolExecutionError("Binary files cannot be read as text.")
        # 保留 BOM 和 CRLF/LF，避免局部编辑顺带改变文件格式。
        return data.decode("utf-8")

    def write_text(self, path: str, content: str, overwrite: bool) -> dict[str, Any]:
        check_text(content, "content", allow_empty=True)
        check_boolean(overwrite, "overwrite")
        target = self.resolve(path, write=True, allow_link=False, kind="file")
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise ToolArgumentsError("Content exceeds the configured text file size limit.")
        existed = target.exists()
        if existed and not target.is_file():
            raise ToolArgumentsError("Target must be a regular file or a new path.")
        if existed and not overwrite:
            raise ToolArgumentsError("File already exists. Set overwrite=true to replace it.")

        self.prepare_parent(target)
        if not overwrite:
            # 独占创建，防止覆盖另一个调用刚刚创建的文件。
            with target.open("xb") as stream:
                stream.write(data)
        else:
            # 在同一目录写好临时文件后替换，避免先清空原文件。
            fd, name = tempfile.mkstemp(prefix=".tabagent-", dir=target.parent)
            temporary = Path(name)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                if existed:
                    shutil.copymode(target, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)

        return {"path": str(target), "bytes_written": len(data), "created": not existed}

    def walk(
            self,
            root: Path,
            *,
            write: bool = False,
            reject_links: bool = False,
    ) -> Iterator[tuple[Path, str]]:
        """遍历真实文件和目录；浏览时跳过链接，递归修改前拒绝链接。"""
        root = self.directory(str(root), write=write)

        def on_error(exc: OSError) -> None:
            raise exc

        for directory, directories, files in os.walk(
                root, followlinks=False, onerror=on_error,
        ):
            current = self.resolve(str(directory), write=write, allow_link=False)
            accepted = []
            for name in sorted(directories):
                target = current / name
                if self.is_link(target):
                    if reject_links:
                        raise ToolArgumentsError("Directory tree contains a link.")
                    continue
                target = self.resolve(str(target), write=write, allow_link=False)
                accepted.append(name)
                yield target, "directory"
            directories[:] = accepted

            for name in sorted(files):
                target = current / name
                if self.is_link(target):
                    if reject_links:
                        raise ToolArgumentsError("Directory tree contains a link.")
                    continue
                target = self.resolve(str(target), write=write, allow_link=False)
                if not target.is_file():
                    if reject_links:
                        raise ToolArgumentsError("Directory tree contains a non-regular file.")
                    continue
                yield target, "file"

    def check_tree(self, root: Path, *, write: bool = False) -> None:
        for count, _ in enumerate(self.walk(root, write=write, reject_links=True), 1):
            if count > self.max_scan_entries:
                raise ToolExecutionError("Directory tree exceeds the configured scan limit.")

    def transfer_paths(
            self,
            source: str,
            destination: str,
            *,
            move: bool,
            overwrite: bool,
    ) -> tuple[Path, Path]:
        """复制、移动使用相同的源路径和目标路径检查。"""
        check_boolean(overwrite, "overwrite")
        src = self.resolve(source, write=move, allow_link=False)
        if not src.is_file() and not src.is_dir():
            raise ToolArgumentsError("Source must be an existing file or directory.")
        kind: Literal["file", "directory"] = "directory" if src.is_dir() else "file"
        dst = self.resolve(destination, write=True, allow_link=False, kind=kind)
        if src == dst or (dst.exists() and src.samefile(dst)):
            raise ToolArgumentsError("Source and destination must be different.")
        if move:
            self.protect_root(src)
        if src.is_dir():
            if dst.is_relative_to(src):
                raise ToolArgumentsError("Destination must not be inside the source directory.")
            if dst.exists():
                raise ToolArgumentsError("Directory destination must not already exist.")
            self.check_tree(src, write=move)
        elif dst.exists():
            if not dst.is_file():
                raise ToolArgumentsError("Destination must be a regular file.")
            if not overwrite:
                raise ToolArgumentsError("Destination exists. Set overwrite=true to replace it.")
        return src, dst
