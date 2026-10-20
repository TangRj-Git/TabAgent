"""持有后台任务，并在有限时间内等待清理；超时不会遗失仍运行的任务。"""

import asyncio
from collections.abc import Coroutine
from typing import Any


def observe(task: asyncio.Task[Any]) -> None:
    """后台错误由所属客户端保存；避免无人等待时出现未检索异常警告。"""
    if not task.cancelled():
        task.exception()


def start_task[T](
    coroutine: Coroutine[Any, Any, T],
    *,
    name: str,
    owner: set[asyncio.Task[Any]] | None = None,
) -> asyncio.Task[T]:
    task = asyncio.create_task(coroutine, name=name)
    task.add_done_callback(observe)
    if owner is not None:
        owner.add(task)
        task.add_done_callback(owner.discard)
    return task


async def finish_cleanup(task: asyncio.Task[None], *, timeout: float) -> None:
    """延迟传播外部取消，但最多等待 timeout 秒；task 的引用由调用方保留。"""
    deadline = asyncio.get_running_loop().time() + timeout
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            # wait 不会像 wait_for 那样在超时后继续等待任务响应取消。
            await asyncio.wait({task}, timeout=remaining)
        except asyncio.CancelledError as exc:
            cancellation = exc
    if cancellation is not None:
        if not task.done():
            cancellation.add_note("MCP cleanup is still pending; the owner retains the cleanup task.")
        raise cancellation
    if not task.done():
        raise TimeoutError("MCP cleanup did not finish within the configured close timeout.")
    task.result()
