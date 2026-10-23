"""管理非交互子进程；Shell 命令构建和工具注册由调用方负责。"""

from __future__ import annotations

import asyncio
import codecs
import math
import os
import shutil
import signal
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, TypeAlias
from uuid import uuid4

from tabagent.core.exceptions import ToolArgumentsError, ToolExecutionError

ProcessTool: TypeAlias = Callable[..., Awaitable[str]]

_MAX_WAIT_SECONDS = 30.0
_OUTPUT_CLOSE_SECONDS = 2.0
_STOP_SECONDS = 3.0


@dataclass
class _OutputBuffer:
    """保留输出尾部；游标使用累计 Unicode 字符数。"""

    limit: int
    text: str = ""
    total: int = 0

    def append(self, text: str) -> None:
        self.total += len(text)
        self.text = (self.text + text)[-self.limit:]

    def read(self, offset: int) -> tuple[str, bool]:
        first = self.total - len(self.text)
        return self.text[max(offset - first, 0):], offset < first


class _ProcessOutput(asyncio.SubprocessProtocol):
    """分开跟踪进程退出与输出管道关闭，持续消费两个输出流。"""

    def __init__(self, limit: int) -> None:
        self.stdout = _OutputBuffer(limit)
        self.stderr = _OutputBuffer(limit)
        self.changed = asyncio.Event()
        self.exited = asyncio.Event()
        self.closed = asyncio.Event()
        self.incomplete = False
        self.error: str | None = None
        self._decoders = {
            fd: codecs.getincrementaldecoder("utf-8")(errors="replace")
            for fd in (1, 2)
        }

    def pipe_data_received(self, fd: int, data: bytes) -> None:
        if fd in self._decoders:
            output = self.stdout if fd == 1 else self.stderr
            output.append(self._decoders[fd].decode(data))
            self.changed.set()

    def pipe_connection_lost(self, fd: int, exc: Exception | None) -> None:
        decoder = self._decoders.pop(fd, None)
        if decoder is not None:
            output = self.stdout if fd == 1 else self.stderr
            output.append(decoder.decode(b"", final=True))
        if exc is not None:
            self.incomplete = True
            self.error = "Process output could not be read completely."
        self.changed.set()

    def process_exited(self) -> None:
        self.exited.set()
        self.changed.set()

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is not None:
            self.incomplete = True
            self.error = "The process output connection failed."
        self.closed.set()
        self.changed.set()


@dataclass
class _Job:
    job_id: str
    command: str
    cwd: str
    process: asyncio.SubprocessTransport
    output: _ProcessOutput
    timeout: float | None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    stop_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    watcher: asyncio.Task[None] | None = None
    stopper: asyncio.Task[None] | None = None
    stop_reason: str | None = None
    timed_out: bool = False
    published: bool = False
    finished_at: float | None = None
    error: str | None = None


def _seconds(value: float, name: str, *, wait: bool = False) -> float:
    rule = "non-negative" if wait else "positive"
    message = f"{name} must be a {rule} finite number."
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolArgumentsError(message)
    try:
        seconds = float(value)
    except OverflowError as exc:
        raise ToolArgumentsError(message) from exc
    if not math.isfinite(seconds) or seconds < 0 or (not wait and seconds == 0):
        raise ToolArgumentsError(message)
    if wait and seconds > _MAX_WAIT_SECONDS:
        raise ToolArgumentsError("wait_time must not exceed 30 seconds.")
    return seconds


def _observe_task(task: asyncio.Task[None]) -> None:
    # 后台清理可在调用方取消等待后继续；异常仍由后续 await 正常传递。
    if not task.cancelled():
        task.exception()


class ProcessManager:
    """
    在同一个事件循环中管理一个 App 的非交互进程，返回 JSON 兼容字典。

    wait_time 只限制调用等待时间；timeout 限制程序运行时间。
    输出按每个流的字符数限制，已结束任务只保留最近 max_finished 个。
    通过 async with 或 aclose() 释放资源；管理器关闭后不可重新启动任务。
    不提供输入、PTY 或跨 App 恢复。进程树清理依赖根进程仍可定位；
    根进程先退出的后代、主动脱离进程树的程序不保证被完整接管。
    """

    def __init__(
            self,
            *,
            max_running: int = 16,
            max_finished: int = 64,
            output_limit: int = 25_600,
    ) -> None:
        for name, value in (
                ("max_running", max_running),
                ("max_finished", max_finished),
                ("output_limit", output_limit),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolArgumentsError(f"{name} must be a positive integer.")

        # 控制这个管理器最多同时管理多少个尚未结束的任务，默认是 16。
        # 这里统计的是管理器中的任务数，不是整个电脑上的进程数。一个任务内部再启动子进程，也不会按每个子进程分别计算。
        # 另外，进程虽然已经退出，但输出和清理工作尚未完成时，也可能暂时计入这个数量。
        self._max_running = max_running

        # 控制最多保留多少条已经结束的任务记录，默认是 64。
        # 任务结束后，没有立即从管理器中消失，因此后续仍然可以查询它的：
        # - 退出状态和退出码。
        # - 已保留的标准输出、错误输出。
        # - 是否超时、是否被停止等信息。
        # 当可清理的已结束记录超过 64 条时，_prune() 会移除较早结束的记录。
        # 它控制的是内存中的历史记录数量，不会删除程序生成的文件，也不会为了腾位置而停止正在运行的任务。
        self._max_finished = max_finished

        # 控制每个任务、每个输出流最多保留多少个字符，默认是 25_600。
        # 因此，一个任务的两个输出缓冲区合起来，最多保留 51,200 个字符。
        # 超过限制时，保留最新的尾部内容，丢弃最早的内容。
        # 达到这个限制不会停止程序。程序仍然可以继续输出，只是旧内容会不断被替换。它也不同于 read() 的 max_output_chars：后者控制一次查询返回多少字符。
        self._output_limit = output_limit

        # 这是管理器的任务记录表。
        # 键 str：任务标识 job_id。
        # 值 _Job：这个任务的完整内部记录。
        self._jobs: dict[str, _Job] = {}

        # 这是一个异步锁，用于保护需要连续完成的共享状态操作。
        # 这个锁不会让所有程序串行运行。 锁在进程创建、记录保存之后就释放了，进程本身可以继续在后台运行。等待程序完成的逻辑位于锁外。
        # 它用于协调同一个事件循环中的协程，不是跨线程锁。
        self._lock = asyncio.Lock()

        # 保存这个管理器所属的事件循环。
        self._loop: asyncio.AbstractEventLoop | None = None

        # 这是一个禁止继续启动任务的状态标记。
        # 这里需要区分：
        # _closed == True 表示已经进入关闭状态，不代表所有清理工作都已成功完成。
        # 即使清理失败，它仍然保持 True，防止继续启动新任务。之后可以再次调用 aclose() 重试清理，但不能重新开放这个管理器来启动任务。
        # 如果需要重新使用，应创建新的 ProcessManager。
        self._closed = False

        # 保存整个管理器的异步清理任务。
        # 保存它主要有三个作用：
        # - 共享清理过程。 多个协程同时调用 aclose() 时，可以等待同一个尚未完成的清理任务。
        # - 检查清理是否结束。 通过 .done() 判断任务是否已经完成。
        # - 支持重试。 上一次清理结束但失败了，后续调用可以重新创建清理任务。
        self._close_task: asyncio.Task[None] | None = None

    def _check_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ToolExecutionError(
                "Process manager must be used on its original event loop."
            )
        return loop

    async def start(
            self,
            argv: list[str],
            *,
            cwd: str | Path,
            command: str | None = None,
            wait_time: float = 2.0,
            timeout: float | None = 120.0,
            env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """启动 argv 中的解释器及参数；command 仅用于展示，不参与执行。"""
        loop = self._check_loop()
        if (
                not isinstance(argv, list)
                or not argv
                or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
                or not argv[0]
        ):
            raise ToolArgumentsError("argv must be a non-empty list of valid strings.")
        if command is not None and not isinstance(command, str):
            raise ToolArgumentsError("command must be a string or None.")
        if env is not None and (
                not isinstance(env, dict)
                or any(
            not isinstance(key, str) or not key or "=" in key or "\0" in key
            or not isinstance(value, str) or "\0" in value
            for key, value in env.items()
        )
        ):
            raise ToolArgumentsError("env must map valid environment names to strings.")
        wait_time = _seconds(wait_time, "wait_time", wait=True)
        if timeout is not None:
            timeout = _seconds(timeout, "timeout")
        try:
            directory = Path(cwd).expanduser().resolve()
            exists = directory.is_dir()
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            raise ToolArgumentsError("cwd could not be resolved.") from exc
        if not exists:
            raise ToolArgumentsError("cwd must be an existing directory.")

        cancelled = False
        async with self._lock:
            if self._closed:
                raise ToolExecutionError("Process manager is closed.")
            self._prune()
            if sum(self._active(job) for job in self._jobs.values()) >= self._max_running:
                raise ToolExecutionError("The running process limit has been reached.")
            output = _ProcessOutput(self._output_limit)
            options = (
                {"creationflags": subprocess.CREATE_NO_WINDOW}
                if os.name == "nt" else {"start_new_session": True}
            )
            spawning = asyncio.create_task(loop.subprocess_exec(
                lambda: output, *argv, cwd=directory, env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **options,
            ))
            try:
                while True:
                    try:
                        process, _ = await asyncio.shield(spawning)
                        break
                    except asyncio.CancelledError:
                        # 先取得句柄再清理，重复取消也不能丢失进程所有权。
                        if spawning.cancelled():
                            raise
                        cancelled = True
            except (OSError, ValueError, TypeError, NotImplementedError) as exc:
                if cancelled:
                    raise asyncio.CancelledError from exc
                raise ToolExecutionError("The process could not be started.") from exc

            job = _Job(
                job_id=f"job_{uuid4().hex}",
                command=command if command is not None else " ".join(argv),
                cwd=str(directory), process=process, output=output, timeout=timeout,
            )
            self._jobs[job.job_id] = job
            job.watcher = asyncio.create_task(self._watch(job))
            job.watcher.add_done_callback(_observe_task)

        try:
            if cancelled:
                raise asyncio.CancelledError
            if wait_time:
                try:
                    await asyncio.wait_for(job.done.wait(), wait_time)
                except TimeoutError:
                    pass
            return self._snapshot(job, 0, 0)
        except asyncio.CancelledError:
            try:
                await self._ensure_stopped(job)
            except ToolExecutionError:
                pass  # 保留任务和错误，关闭 App 时可再次尝试清理。
            raise
        finally:
            job.published = True

    async def read(
            self,
            job_id: str,
            *,
            cursor: str | None = None,
            wait_time: float = 0.0,
            max_output_chars: int | None = None,
    ) -> dict[str, Any]:
        """读取新增输出；可限制每个流的返回字符数，游标只越过已返回的内容。"""
        loop = self._check_loop()
        job = self._get(job_id)
        wait_time = _seconds(wait_time, "wait_time", wait=True)
        if max_output_chars is not None and (
                type(max_output_chars) is not int or not 1 <= max_output_chars <= 50_000
        ):
            raise ToolArgumentsError("max_output_chars must be an integer between 1 and 50000, or None.")
        out_offset = err_offset = 0
        if cursor is not None:
            try:
                owner, out_text, err_text = cursor.split(":")
                out_offset, err_offset = int(out_text), int(err_text)
                if (
                        owner != job_id
                        or not 0 <= out_offset <= job.output.stdout.total
                        or not 0 <= err_offset <= job.output.stderr.total
                ):
                    raise ValueError
            except (AttributeError, TypeError, ValueError) as exc:
                raise ToolArgumentsError("cursor is invalid for this job.") from exc

        deadline = loop.time() + wait_time
        while (
                not job.done.is_set()
                and job.output.stdout.total == out_offset
                and job.output.stderr.total == err_offset
                and job.error is None and job.output.error is None
        ):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            job.output.changed.clear()
            try:
                await asyncio.wait_for(job.output.changed.wait(), remaining)
            except TimeoutError:
                break
        return self._snapshot(job, out_offset, err_offset, max_output_chars)

    async def stop(self, job_id: str) -> dict[str, Any]:
        """强制停止指定任务；重复停止已结束任务不会改变原来的退出状态。"""
        self._check_loop()
        job = self._get(job_id)
        await self._ensure_stopped(job)
        return self._snapshot(job, 0, 0)

    async def list_jobs(self, *, include_finished: bool = False) -> dict[str, Any]:
        """只列出当前管理器持有的任务，不枚举系统中的其他进程。"""
        self._check_loop()
        if not isinstance(include_finished, bool):
            raise ToolArgumentsError("include_finished must be a boolean.")
        self._prune()
        return {"jobs": [
            {
                "job_id": job.job_id, "command": job.command, "cwd": job.cwd,
                "status": self._status(job), "exit_code": job.process.get_returncode(),
                "timed_out": job.timed_out, "error": job.error or job.output.error,
            }
            for job in self._jobs.values()
            if include_finished or self._active(job)
        ]}

    async def aclose(self) -> None:
        """禁止新任务，并清理已有任务；关闭失败后允许再次调用重试。"""
        self._check_loop()
        if self._close_task is None or self._close_task.done():
            self._closed = True
            self._close_task = asyncio.create_task(self._close_all())
            self._close_task.add_done_callback(_observe_task)
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._close_task)
            raise

    async def __aenter__(self) -> ProcessManager:
        self._check_loop()
        if self._closed:
            raise ToolExecutionError("Process manager is closed.")
        return self

    async def __aexit__(
            self, exc_type: type[BaseException] | None,
            exc_value: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _get(self, job_id: str) -> _Job:
        if not isinstance(job_id, str) or not job_id:
            raise ToolArgumentsError("job_id must be a non-empty string.")
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise ToolExecutionError("The job does not exist or has expired.") from exc

    @staticmethod
    def _active(job: _Job) -> bool:
        return job.process.get_returncode() is None or not job.done.is_set()

    @staticmethod
    def _status(job: _Job) -> str:
        code = job.process.get_returncode()
        if code is None:
            return "stopping" if job.stop_reason else "running"
        return job.stop_reason or ("completed" if code == 0 else "failed")

    def _snapshot(
            self, job: _Job, out_offset: int, err_offset: int,
            max_output_chars: int | None = None,
    ) -> dict[str, Any]:
        stdout, out_truncated = job.output.stdout.read(out_offset)
        stderr, err_truncated = job.output.stderr.read(err_offset)
        stdout = stdout[:max_output_chars]
        stderr = stderr[:max_output_chars]
        out_dropped = max(0, job.output.stdout.total - len(job.output.stdout.text) - out_offset)
        err_dropped = max(0, job.output.stderr.total - len(job.output.stderr.text) - err_offset)
        # 缓冲区已丢失的内容无法重读；仍保留但本次未返回的内容不能被游标跳过。
        out_next = out_offset + out_dropped + len(stdout)
        err_next = err_offset + err_dropped + len(stderr)
        return {
            "job_id": job.job_id, "status": self._status(job),
            "exit_code": job.process.get_returncode(),
            "stdout": stdout, "stderr": stderr,
            "next_cursor": f"{job.job_id}:{out_next}:{err_next}",
            "stdout_truncated": out_truncated, "stderr_truncated": err_truncated,
            "stdout_total_chars": job.output.stdout.total,
            "stderr_total_chars": job.output.stderr.total,
            "stdout_dropped_chars": out_dropped, "stderr_dropped_chars": err_dropped,
            "output_limit_chars": self._output_limit,
            "has_more_output": (
                    out_next < job.output.stdout.total or err_next < job.output.stderr.total
            ),
            "timed_out": job.timed_out,
            "output_complete": job.done.is_set() and not job.output.incomplete,
            "error": job.error or job.output.error,
        }

    async def _watch(self, job: _Job) -> None:
        try:
            try:
                await asyncio.wait_for(job.output.exited.wait(), job.timeout)
            except TimeoutError:
                # 与手动停止共用锁，等待其结束后再判断是否仍需超时终止。
                try:
                    await self._signal_stop(job, "timed_out")
                except ToolExecutionError:
                    pass  # 保留实际状态和错误，允许用户重试停止。
                await job.output.exited.wait()

            try:
                await asyncio.wait_for(job.output.closed.wait(), _OUTPUT_CLOSE_SECONDS)
            except TimeoutError:
                job.output.incomplete = True
                job.output.error = "Output pipes remained open after the process exited."
        except asyncio.CancelledError:
            job.output.incomplete = True
            job.error = "Process monitoring was interrupted."
            try:
                await self._signal_stop(job, "stopped")
            except ToolExecutionError:
                pass
            raise
        finally:
            # 使用公开的 transport.close() 回收管道，避免 EOF 缺失造成资源泄漏。
            # 停止失败且进程仍存活时保留句柄，供后续 stop/aclose 重试。
            if job.process.get_returncode() is not None:
                job.process.close()
                await job.output.closed.wait()
            job.finished_at = asyncio.get_running_loop().time()
            job.done.set()
            job.output.changed.set()
            self._prune()

    async def _signal_stop(self, job: _Job, reason: str) -> None:
        async with job.stop_lock:
            if job.process.get_returncode() is not None:
                return
            if reason == "timed_out":
                job.timed_out = True
            job.stop_reason = reason
            job.output.changed.set()
            try:
                await self._terminate(job)
                if job.error == "Process termination could not be confirmed.":
                    job.error = None
            except (OSError, TimeoutError, ToolExecutionError) as exc:
                if job.process.get_returncode() is None:
                    job.stop_reason = None
                job.error = "Process termination could not be confirmed."
                job.output.changed.set()
                raise ToolExecutionError(job.error) from exc

    async def _ensure_stopped(self, job: _Job) -> None:
        if job.stopper is None or job.stopper.done():
            job.stopper = asyncio.create_task(self._stop_job(job))
            job.stopper.add_done_callback(_observe_task)
        await asyncio.shield(job.stopper)

    async def _stop_job(self, job: _Job) -> None:
        await self._signal_stop(job, "stopped")
        try:
            await asyncio.wait_for(job.done.wait(), _OUTPUT_CLOSE_SECONDS + 1)
        except TimeoutError as exc:
            job.error = "Process cleanup did not finish in time."
            raise ToolExecutionError(job.error) from exc

    @staticmethod
    async def _terminate(job: _Job) -> None:
        if os.name == "nt":
            executable = shutil.which("taskkill")
            if executable is None:
                raise ToolExecutionError("taskkill is not available.")
            killer = await asyncio.create_subprocess_exec(
                executable, "/PID", str(job.process.get_pid()), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                await asyncio.wait_for(killer.wait(), 5.0)
            finally:
                if killer.returncode is None:
                    killer.kill()
                    await killer.wait()
            if killer.returncode != 0 and job.process.get_returncode() is None:
                raise ToolExecutionError("The process tree could not be terminated.")
        else:
            try:
                os.killpg(job.process.get_pid(), signal.SIGKILL)
            except ProcessLookupError:
                pass
        await asyncio.wait_for(job.output.exited.wait(), _STOP_SECONDS)

    async def _close_all(self) -> None:
        async with self._lock:
            jobs = list(self._jobs.values())
        results = await asyncio.gather(
            *(self._ensure_stopped(job) for job in jobs), return_exceptions=True,
        )
        if any(isinstance(result, BaseException) for result in results):
            raise ToolExecutionError("Some process jobs could not be closed.")

    def _prune(self) -> None:
        finished = sorted(
            (job for job in self._jobs.values()
             if job.published and not self._active(job)),
            key=lambda job: job.finished_at or 0,
        )
        for job in finished[:-self._max_finished]:
            self._jobs.pop(job.job_id, None)
