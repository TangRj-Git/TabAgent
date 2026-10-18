"""一个等待执行结束的 Shell 工具：Windows 使用 PowerShell，Linux 使用 Bash。"""

import asyncio
import base64
import json
import math
import os
import shutil
import signal
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError

SHELL_PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "PowerShell on Windows, Bash on Linux. No interactive input."},
        "cwd": {"type": "string", "description": "Working directory; '.' uses the fixed workspace."},
        "timeout": {"type": "number", "exclusiveMinimum": 0,
                    "description": "Execution timeout in seconds; normally 120."},
    },
    "required": ["command", "cwd", "timeout"],
    "additionalProperties": False,
}

_STREAM_BYTES = 25 * 1024
_STREAM_LINES = 1000


def _shell_command(command: str) -> list[str]:
    if os.name == "nt":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            raise ToolExecutionError("PowerShell is not installed or is not on PATH.")
        # 固定 PowerShell 的管道编码，并保留本机程序的非零退出码。
        script = (
                "$ErrorActionPreference = 'Stop'\n"
                "$utf8 = [System.Text.UTF8Encoding]::new($false)\n"
                "[Console]::InputEncoding = $utf8\n"
                "[Console]::OutputEncoding = $utf8\n"
                "$OutputEncoding = $utf8\n"
                "$global:LASTEXITCODE = 0\n"
                "try {\n& {\n" + command + "\n}\n"
                                           "$commandSucceeded = $?\n"
                                           "if (-not $commandSucceeded -and $LASTEXITCODE -eq 0) { exit 1 }\n"
                                           "exit $LASTEXITCODE\n"
                                           "} catch {\n[Console]::Error.WriteLine($_.ToString())\nexit 1\n}\n"
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]

    executable = shutil.which("bash")
    if executable is None:
        raise ToolExecutionError("Bash is not installed or is not on PATH.")
    return [executable, "--noprofile", "--norc", "-c", command]


class _OutputTail:
    """持续消费管道，仅保留尾部，避免大量输出堵塞进程或占满内存。"""

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
        truncated = self.total_bytes > len(self.data) or len(lines) > _STREAM_LINES
        return "".join(lines[-_STREAM_LINES:]), truncated


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """停止普通子进程树；Shell 执行仍使用宿主进程的系统权限。"""
    if os.name == "nt":
        if process.returncode is None:
            taskkill = shutil.which("taskkill")
            if taskkill:
                try:
                    killer = await asyncio.create_subprocess_exec(
                        taskkill, "/PID", str(process.pid), "/T", "/F",
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
        # 即便 shell 已退出，同组子进程仍可能持有 stdout/stderr 管道。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


def create_shell_tool(workspace: str | Path) -> Callable[..., Awaitable[str]]:
    """绑定默认目录并返回 shell 函数，不改变 Python 进程的 cwd。"""
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ToolArgumentsError("workspace must be an existing directory.")

    async def shell(command: str, cwd: str = ".", timeout: float = 120.0) -> str:
        """Run one non-interactive command and wait for its final result.

        Windows uses PowerShell; Linux uses Bash. Relative cwd uses the fixed
        workspace; absolute cwd does not change that default. This is not a
        filesystem sandbox. Timeout or cancellation attempts to stop the process
        tree. Detached background jobs are not supported. stdout and stderr each
        retain at most the last 25 KiB / 1,000 lines; truncation is reported.
        Output is decoded as UTF-8, replacing invalid bytes. No process polling
        tool is needed. Command failures return exit_code, stdout, and stderr.
        """
        if not isinstance(command, str) or not command.strip() or "\0" in command:
            raise ToolArgumentsError("command must be non-empty text without null bytes.")
        if (
                isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0
        ):
            raise ToolArgumentsError("timeout must be a positive finite number of seconds.")
        if not isinstance(cwd, str) or not cwd or "\0" in cwd:
            raise ToolArgumentsError("cwd must be a non-empty directory path without null bytes.")
        directory = Path(cwd).expanduser()
        directory = (root / directory).resolve() if not directory.is_absolute() else directory.resolve()
        if not directory.is_dir():
            raise ToolArgumentsError(f"Working directory does not exist: {cwd!r}.")
        arguments = _shell_command(command)
        environment = os.environ.copy()
        environment.setdefault("PYTHONIOENCODING", "utf-8")
        platform_options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt" else {"start_new_session": True}
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments, cwd=directory, env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                **platform_options,
            )
        except OSError as exc:
            raise ToolExecutionError("The shell process could not be started.") from exc

        stdout, stderr = _OutputTail(), _OutputTail()
        completed = asyncio.gather(
            process.wait(), stdout.read(process.stdout), stderr.read(process.stderr),
        )
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.shield(completed), timeout)
        except asyncio.TimeoutError:
            timed_out = True
        finally:
            if not completed.done():
                await _terminate(process)
                try:
                    await asyncio.wait_for(asyncio.shield(completed), 3)
                except asyncio.TimeoutError:
                    completed.cancel()
                    await asyncio.gather(completed, return_exceptions=True)

        output, output_truncated = stdout.result()
        error, error_truncated = stderr.result()
        return json.dumps({
            "exit_code": process.returncode, "stdout": output, "stderr": error,
            "timed_out": timed_out, "stdout_truncated": output_truncated,
            "stderr_truncated": error_truncated,
        }, ensure_ascii=False)

    return shell
