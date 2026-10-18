"""Shell 工具共用的目录、进程执行、输出收集和超时处理。"""

import asyncio
import json
import math
import os
import platform
import shutil
import signal
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeAlias

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError

ShellTool: TypeAlias = Callable[..., Awaitable[str]]

_STREAM_BYTES = 25 * 1024
_STREAM_LINES = 1000


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    # 非交互 Bash 仍会读取 BASH_ENV；工具不加载这个额外启动脚本。
    environment.pop("BASH_ENV", None)
    return environment


class _OutputTail:
    """持续消费输出，仅保留尾部，避免大量输出堵塞管道或占满内存。"""

    def __init__(self) -> None:
        self.data = bytearray()
        self.total_bytes = 0

    async def read(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(8192):
            self.total_bytes += len(chunk)
            self.data.extend(chunk)
            if len(self.data) > _STREAM_BYTES:
                del self.data[:-_STREAM_BYTES]

    def result(self) -> tuple[str, bool]:
        text = self.data.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        truncated = (
                self.total_bytes > len(self.data)
                or len(lines) > _STREAM_LINES
        )
        return "".join(lines[-_STREAM_LINES:]), truncated


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """尝试停止本次启动的进程树，不支持脱离进程组的后台任务。"""
    if os.name == "nt":
        if process.returncode is None:
            taskkill = shutil.which("taskkill")
            if taskkill:
                try:
                    killer = await asyncio.create_subprocess_exec(
                        taskkill,
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    try:
                        await asyncio.wait_for(killer.wait(), 5)
                    except asyncio.TimeoutError:
                        killer.kill()
                        await killer.wait()
                except OSError:
                    pass
    else:
        # Shell 已退出时，同组子进程仍可能持有 stdout/stderr 管道。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


class BaseShell:
    """绑定默认目录和实际解释器，每次调用启动独立的非交互进程。"""

    def __init__(
            self,
            workspace: str | Path,
            *,
            name: str,
            executable_names: tuple[str, ...],
            version_arguments: list[str],
            build_arguments: Callable[[str], list[str]],
    ) -> None:
        try:
            self.workspace = Path(workspace).expanduser().resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolArgumentsError("workspace could not be resolved.") from exc

        if not self.workspace.is_dir():
            raise ToolArgumentsError("workspace must be an existing directory.")

        self.name = name
        self._build_arguments = build_arguments

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

        # 初始化时读取一次版本，后续调用复用解释器及其说明。
        try:
            result = subprocess.run(
                [self.executable, *version_arguments],
                cwd=self.workspace,
                env=_environment(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolExecutionError(
                f"The {name} version could not be determined."
            ) from exc

        if result.returncode != 0 or not result.stdout.strip():
            raise ToolExecutionError(
                f"The {name} version could not be determined."
            )
        self.version = result.stdout.strip().splitlines()[0]

    def description(self) -> str:
        """生成当前解释器的实际运行环境说明，供注册工具时使用。"""
        return (
            f"Run non-interactive {self.name} commands on {platform.system()} "
            "and wait for the final result.\n"
            f"Shell version: {self.version}. Use {self.name} syntax.\n"
            f"Default workspace: {self.workspace}. Relative cwd paths use "
            "this directory; absolute paths do not change the default.\n"
            "Each call starts a new process. Directory and environment changes "
            "do not persist between calls. Interactive input and detached "
            "background jobs are not supported.\n"
            "Returns JSON containing exit_code, stdout, stderr, timed_out, "
            "stdout_truncated, and stderr_truncated. Each output stream retains "
            "at most its last 25 KiB / 1,000 lines. Output is decoded as UTF-8 "
            "with replacement for invalid bytes.\n"
            "Timeout or cancellation attempts to stop the process tree. "
            "Commands run with the host process permissions; the workspace "
            "is a path base, not a filesystem sandbox."
        )

    async def run(
            self,
            command: str,
            cwd: str = ".",
            timeout: float = 120.0,
    ) -> str:
        if not isinstance(command, str) or not command.strip() or "\0" in command:
            raise ToolArgumentsError(
                "command must be non-empty text without null bytes."
            )
        if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or timeout <= 0
        ):
            raise ToolArgumentsError(
                "timeout must be a positive finite number of seconds."
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

        arguments = [self.executable, *self._build_arguments(command)]
        platform_options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                cwd=directory,
                env=_environment(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **platform_options,
            )
        except OSError as exc:
            raise ToolExecutionError(
                f"The {self.name} process could not be started."
            ) from exc

        stdout = _OutputTail()
        stderr = _OutputTail()
        completed = asyncio.gather(
            process.wait(),
            stdout.read(process.stdout),
            stderr.read(process.stderr),
        )
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.shield(completed), timeout)
        except asyncio.TimeoutError:
            timed_out = True
        finally:
            if not completed.done() or process.returncode is None:
                await _terminate(process)
                try:
                    await asyncio.wait_for(asyncio.shield(completed), 3)
                except asyncio.TimeoutError:
                    completed.cancel()
                    await asyncio.gather(completed, return_exceptions=True)

        output, output_truncated = stdout.result()
        error, error_truncated = stderr.result()
        return json.dumps(
            {
                "exit_code": process.returncode,
                "stdout": output,
                "stderr": error,
                "timed_out": timed_out,
                "stdout_truncated": output_truncated,
                "stderr_truncated": error_truncated,
            },
            ensure_ascii=False,
        )
