"""持有后台任务，并在有限时间内等待清理；超时不会遗失仍运行的任务。"""

import asyncio
from collections.abc import Coroutine
from typing import Any

"""
在这里，[] 用来指定泛型的类型参数。
对于 asyncio.Task[T]，T 表示任务正常完成后的返回值类型，也就是 await task 得到的结果类型：
asyncio.Task[int]   # await task 得到 int
asyncio.Task[str]   # await task 得到 str
asyncio.Task[None]  # await task 得到 None
asyncio.Task[Any]   # 不限定任务返回值的类型

Coroutine[Any, Any, T] 是协程对象的类型注解。它的三个类型参数分别对应：
Coroutine[YieldType, SendType, ReturnType]
位置	    含义	                                            你的写法
第一个	协程挂起时，通过底层协议向外产出的值的类型	            Any：不限制
第二个	外部通过 .send(...) 向协程发送的值的类型	            Any：不限制
第三个	协程正常结束时返回的结果类型，也就是 await 得到的类型	T：由具体协程决定
前两个主要涉及协程的底层运行机制，普通 async/await 代码里通常由事件循环等机制负责处理，因此经常写成 Any。平时最需要关注的是第三个参数。
"""


def observe(task: asyncio.Task[Any]) -> None:
    """后台错误由所属客户端保存；避免无人等待时出现未检索异常警告。"""
    if not task.cancelled():
        task.exception()


# 定义泛型函数，T 表示协程正常结束时返回的数据类型。
def start_task[T](
        coroutine: Coroutine[Any, Any, T],  # 待执行的协程对象，最终返回值类型为 T
        *,  # 后面的参数必须通过参数名传入
        name: str,  # 任务名称，用于调试、日志和识别任务
        owner: set[asyncio.Task[Any]] | None = None,  # 可选的任务集合，用于集中跟踪任务
) -> asyncio.Task[T]:  # 返回 Task 对象；await 这个任务得到的结果类型为 T
    """
    空集合 set() 和 None 不同：前者是已创建但没有元素的集合，后者在这里表示未提供集合。
    虽然 bool(set()) 和 bool(None) 都是 False，但空集合并不是 None，仍然可以添加元素。
    因此使用 `if owner is not None`：只要提供了集合，即使为空，也执行 owner.add(task)。
    如果改成 `if owner`，空集合会被视为 False，导致跳过任务登记。
    """
    task = asyncio.create_task(  # 将协程包装成任务，交给当前事件循环调度执行
        coroutine,  # 指定要执行的协程对象
        name=name,  # 为创建的任务设置名称
    )

    # 注册完成回调：任务结束后调用 observe(task)。
    # 正常返回、因异常结束、完成取消，都会触发完成回调。
    task.add_done_callback(observe)

    # _work 一开始不是 None
    # 实际的 owner 是那个空集合，而不是默认的 None
    # 这里检查的是“是不是 None”，不是“集合有没有内容”
    # 所以即使集合为空，也会执行：
    # owner.add(task)
    # 结论：第一次创建 _open(...) 的任务时，它就会被加入 _work。
    if owner is not None:  # 如果调用方提供了任务集合，即使集合为空也进入此分支
        owner.add(task)  # 保存任务引用，方便后续统一等待、取消或检查状态

        # 注册另一个完成回调：任务结束后调用 owner.discard(task)，自动移出集合。
        # discard 在任务已经不在集合中时也不会报错。
        task.add_done_callback(owner.discard)

    return task  # 返回任务对象，调用方可以 await task、task.cancel() 或 task.done()


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
