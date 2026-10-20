"""Shell 工具共用的目录、解释器配置和托管进程执行。"""

import asyncio
import json
import os
import platform
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeAlias

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError
from tabagent.tool.tools.process import ProcessManager

ShellTool: TypeAlias = Callable[..., Awaitable[str]]


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    # 非交互 Bash 仍会读取 BASH_ENV；工具不加载这个额外启动脚本。
    environment.pop("BASH_ENV", None)
    return environment


class BaseShell:
    """
    绑定默认目录和解释器，由 ProcessManager 执行非交互进程。

    共享管理器由调用方创建和关闭，不能在每次 run() 后关闭。
    未传入共享管理器时，使用临时管理器并等待执行结束，兼容现有工具工厂。
    """

    def __init__(
            self,
            workspace: str | Path,
            *,
            name: str,
            executable_names: tuple[str, ...],
            version_arguments: list[str],
            build_arguments: Callable[[str], list[str]],
            process_manager: ProcessManager | None = None,
    ) -> None:
        try:
            self.workspace = Path(workspace).expanduser().resolve()
        except (TypeError, OSError, RuntimeError, ValueError) as exc:
            raise ToolArgumentsError("workspace could not be resolved.") from exc

        if not self.workspace.is_dir():
            raise ToolArgumentsError("workspace must be an existing directory.")

        self.name = name
        self._build_arguments = build_arguments
        self._version_arguments = list(version_arguments)
        self._version_lock = asyncio.Lock()
        self._process_manager = process_manager
        self.version: str | None = None

        for executable_name in executable_names:
            executable = shutil.which(executable_name)
            if executable is not None:
                # 固定绝对路径，避免执行目录变化影响解释器定位。
                self.executable = str(Path(executable).resolve())
                break
        else:
            raise ToolExecutionError(
                f"{name} is not installed or is not on PATH."
            )

    async def _ensure_version(self) -> None:
        """首次异步查询版本；临时管理器避免把内部查询混入用户任务列表。"""
        if self.version is not None:
            return

        async with self._version_lock:
            if self.version is not None:
                return

            result = await self._run_to_completion(
                self._version_arguments,
                self.workspace,
                timeout=5.0,
                wait_time=5.0,
            )
            if (
                    result["status"] != "completed"
                    or result["exit_code"] != 0
                    or result["error"] is not None
                    or not result["output_complete"]
                    or not result["stdout"].strip()
            ):
                raise ToolExecutionError(
                    f"The {self.name} version could not be determined."
                )
            self.version = result["stdout"].strip().splitlines()[0]

    def description(self) -> str:
        """说明实际执行方式、工作目录、返回字段和后续查询方式。"""
        if self._process_manager is not None:
            execution = (
                "After startup, wait up to wait_time seconds for completion "
                "(0 to 30; normally 2). Reaching wait_time does not stop the job.\n"
                "Returns job_id, status, exit_code, stdout, stderr, next_cursor, "
                "timed_out, output_complete, error, stdout_truncated, "
                "stderr_truncated, and shell_version.\n"
                "Use process_read with job_id and next_cursor for new output, "
                "process_list to find jobs, and process_stop to stop a job. "
                "A running status does not establish application readiness.\n"
                "Completion does not automatically notify the model; use "
                "process_read to check the result when needed.\n"
                "After a running job is returned, it continues until it exits, "
                "reaches timeout, is stopped, or its manager is closed.\n"
                "Set timeout to null for no runtime deadline.\n"
            )
        else:
            execution = (
                "Wait for the final result.\n"
                "Returns status, exit_code, stdout, stderr, timed_out, "
                "output_complete, error, stdout_truncated, stderr_truncated, "
                "and shell_version. No reusable job_id or cursor is returned.\n"
            )
        return (
            f"Run non-interactive {self.name} commands on {platform.system()}.\n"
            f"Shell executable: {self.executable}. Use {self.name} syntax.\n"
            "Use this for builds, tests, Git, and other command-line programs. "
            "Prefer list_directory/find_paths/search_text/read_file/write_file/"
            "edit_file for their supported file operations, and calculate for "
            "supported arithmetic.\n"
            f"{execution}"
            "timeout limits total process runtime in seconds; normally 120. "
            "Reaching timeout attempts to terminate the process, not pause it.\n"
            "The shell version is detected once on first use and returned "
            "as shell_version; this initial check adds startup time.\n"
            f"Default workspace: {self.workspace}. Relative cwd paths use "
            "this directory; absolute paths do not change the default.\n"
            "Each call starts a new process. Directory and environment changes "
            "do not persist between calls. Interactive input is not supported.\n"
            "Keep long-running programs attached to the shell command. "
            "Detached descendants and descendants whose root has already exited "
            "are not guaranteed to be tracked or stopped.\n"
            "Output is decoded as UTF-8 with replacement for invalid bytes. "
            "Only a bounded tail of each stream is retained, measured in "
            "Unicode characters; check the truncation flags for lost output.\n"
            "Timeout or cancellation while this call is waiting attempts to "
            "stop the process tree. Commands run with the host process "
            "permissions; the workspace is a path base, not a filesystem sandbox."
        )

    async def run(
            self,
            command: str,
            cwd: str = ".",
            timeout: float | None = 120.0,
            *,
            wait_time: float = 2.0,
    ) -> str:
        """执行命令；共享管理器模式下可以在进程结束前返回任务标识。"""
        if not isinstance(command, str) or not command.strip() or "\0" in command:
            raise ToolArgumentsError(
                "command must be non-empty text without null bytes."
            )
        if not isinstance(cwd, str) or not cwd or "\0" in cwd:
            raise ToolArgumentsError(
                "cwd must be a non-empty directory path without null bytes."
            )

        try:
            directory = Path(cwd).expanduser()
            if not directory.is_absolute():
                directory = self.workspace / directory
            directory = directory.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolArgumentsError("cwd could not be resolved.") from exc

        if not directory.is_dir():
            raise ToolArgumentsError(
                f"Working directory does not exist: {cwd!r}."
            )

        await self._ensure_version()
        arguments = self._build_arguments(command)

        # 等待时间、运行时限和输出缓冲统一交给 ProcessManager 校验和管理。
        if self._process_manager is not None:
            result = await self._process_manager.start(
                [self.executable, *arguments],
                cwd=directory,
                command=command,
                wait_time=wait_time,
                timeout=timeout,
                env=_environment(),
            )
        else:
            result = await self._run_to_completion(
                arguments,
                directory,
                timeout,
                wait_time=wait_time,
                command=command,
            )
            # 临时管理器已经关闭，避免返回无法继续查询的标识。
            result.pop("job_id")
            result.pop("next_cursor")

        result["shell_version"] = self.version
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    async def _run_to_completion(
            self,
            arguments: list[str],
            directory: Path,
            timeout: float | None,
            *,
            wait_time: float = 2.0,
            command: str | None = None,
    ) -> dict[str, Any]:
        """版本查询和兼容调用使用临时管理器，结束或取消时释放其资源。"""
        async with ProcessManager(max_running=1, max_finished=1) as manager:
            result = await manager.start(
                [self.executable, *arguments],
                cwd=directory,
                command=command,
                wait_time=wait_time,
                timeout=timeout,
                env=_environment(),
            )
            job_id = result["job_id"]
            while result["exit_code"] is None:
                if result["error"] is not None:
                    raise ToolExecutionError(
                        f"The {self.name} process could not be completed: "
                        f"{result['error']}"
                    )
                result = await manager.read(
                    job_id,
                    cursor=result["next_cursor"],
                    wait_time=30.0,
                )

        # aclose() 等待输出管道回收后，再读取完整的保留输出。
        return await manager.read(job_id)
