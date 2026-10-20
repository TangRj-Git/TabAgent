import asyncio
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any, Optional, Self, AsyncGenerator, Sequence

from tabagent.core.agent import TabAgent
from tabagent.core.exceptions import TabAgentError
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message
from tabagent.core.middleware import MiddlewareManager
from tabagent.middleware.base_middleware import BaseMiddleware, AppInitRequest
from tabagent.tool.registry import ToolRegistry
from tabagent.tool.tools import ProcessManager


class TabAgentApp:
    """
    TabAgent 的统一使用入口。

    接收 LLM 和 Agent 的初始化配置，
    创建内部对象，并管理 LLM 客户端的关闭。
    """

    def __init__(
            self,
            *,
            # LLM 连接配置。
            base_url: str,
            api_key: str,

            # 默认项目目录。
            workspace: str | Path,

            # Agent 配置。
            model: str,
            instructions: Optional[str] = None,
            tool_registry: Optional[ToolRegistry] = None,
            max_model_calls: int = 10,

            # LLM 请求配置。
            timeout: Optional[float] = 60.0,
            max_retries: int = 3,

            # LLM 供应商配置。
            provider: str = "openai",

            # Middleware 配置。
            middlewares: Sequence[BaseMiddleware] = (),
    ) -> None:
        # 在创建 App 时固定绝对路径。
        # 如果传入相对路径，以此时进程的工作目录为基准。
        workspace_path = Path(workspace).expanduser().resolve()

        self._config = AppInitRequest(
            base_url=base_url,
            api_key=api_key,
            workspace=workspace_path,
            model=model,
            instructions=instructions,
            tool_registry=tool_registry,
            max_model_calls=max_model_calls,
            timeout=timeout,
            max_retries=max_retries,
            provider=provider,
        )

        self._middleware_manager = MiddlewareManager(tuple(middlewares))

        # 初始化中间件包围的是整个 _initialize(request)，也就是创建 LLM 和 Agent 的过程。
        # 在进入这个过程之前，可以修改 AppInitRequest 中的参数。
        self._init_handler = self._middleware_manager.build_init(self._initialize)

        self._llm: Optional[TabAgentLLM] = None
        self._agent: Optional[TabAgent] = None

        self._process_manager: Optional[ProcessManager] = None

        # 初始化和关闭共用此锁，避免两个生命周期操作交错修改资源。
        self._lifecycle_lock = asyncio.Lock()

        # 记录当前执行生命周期操作的任务，防止同一任务递归获取锁。
        self._lifecycle_owner: asyncio.Task[Any] | None = None

        # 只有全部初始化中间件执行成功后，才设置为 True。
        self._is_open = False

    async def _initialize(
            self,
            request: AppInitRequest,
    ) -> None:
        # 初始化阶段：创建 LLM 和 Agent，保存后续运行使用的默认配置。
        #
        # 运行阶段：每次执行任务时，根据默认配置创建新的 AgentRequest。
        # 中间件可以在交给下一层执行之前，修改本次运行的模型、指令、工具注册表、调用次数上限，或者替换本次使用的、已经初始化好的 LLM 客户端。
        # Agent 最终使用经过中间件处理后的请求参数执行任务。
        #
        # 修改请求中的配置字段或替换客户端引用，不会自动修改 Agent 保存的默认配置。
        # 但如果直接修改共享对象的内部状态，仍可能影响其他运行。

        if self._llm is not None:
            raise TabAgentError(
                "App resources have already been initialized."
            )

        self._llm = TabAgentLLM(
            base_url=request.base_url,
            api_key=request.api_key,
            provider=request.provider,
            timeout=request.timeout,
            max_retries=request.max_retries,
        )

        self._agent = TabAgent(
            llm=self._llm,
            model=request.model,
            instructions=request.instructions,
            tool_registry=request.tool_registry,
            max_model_calls=request.max_model_calls,
            middleware_manager=self._middleware_manager,
        )

    async def astream(
            self,
            messages: list[Message],
    ) -> AsyncGenerator[str, None]:
        """
        执行 Agent，并向外传递文本增量。

        messages 直接交给 Agent。
        Agent 追加的模型输出和工具结果会保留在原列表中。
        """

        agent = self._agent

        if not self._is_open or agent is None:
            raise TabAgentError(
                "TabAgentApp is not open. "
                "Use 'async with TabAgentApp(...)' before streaming."
            )

        # aclosing() 的作用，就是把生成器包装成可用于 async with 的对象，并在退出时调用它的 aclose()。
        # 异步生成器对象自带 aclose() 方法，由 Python 提供，不需要你自己实现。
        async with aclosing(agent.astream(messages=messages)) as stream:
            async for delta in stream:
                yield delta

    async def _close_resources(self) -> None:
        """
        释放本实例拥有的资源。

        仅供已经持有生命周期锁的内部代码调用。
        关闭失败时保留对应引用，允许后续重试。
        """
        # 关闭开始后，不再接受新的 Agent 运行。
        self._is_open = False
        self._agent = None

        process_manager = self._process_manager
        llm = self._llm

        try:
            if process_manager is not None:
                await process_manager.aclose()

                if self._process_manager is process_manager:
                    self._process_manager = None

        finally:
            # 即使进程清理失败，也尝试关闭 LLM 客户端。
            if llm is not None:
                await llm.aclose()

                if self._llm is llm:
                    self._llm = None

    async def aclose(self) -> None:
        """
        等待正在进行的初始化或关闭操作结束，再清理资源。

        允许重复调用。
        """
        task = asyncio.current_task()
        if task is not None and self._lifecycle_owner is task:
            raise TabAgentError(
                "Cannot close the app from its initialization or cleanup. "
                "Raise an exception to abort initialization."
            )

        async with self._lifecycle_lock:
            self._lifecycle_owner = task
            try:
                await self._close_resources()
            finally:
                self._lifecycle_owner = None

    async def __aenter__(self) -> Self:
        """
        创建本次 App 使用的资源。

        全部初始化中间件执行成功后，才允许 Agent 运行。
        """
        task = asyncio.current_task()
        if task is not None and self._lifecycle_owner is task:
            raise TabAgentError(
                "Cannot open the app from its initialization or cleanup."
            )

        async with self._lifecycle_lock:
            if (
                    self._is_open
                    or self._llm is not None
                    or self._process_manager is not None
            ):
                raise TabAgentError(
                    "TabAgentApp is already open or still has resources to close."
                )

            self._lifecycle_owner = task

            try:
                # 必须在初始化中间件执行之前创建。
                # 每次重新打开 App，都使用新的管理器。
                self._process_manager = ProcessManager()

                # 为本次初始化创建请求，保留原始默认配置。
                # 这里只传递管理器引用，不复制管理器。
                request = replace(
                    self._config,
                    process_manager=self._process_manager,
                )

                if request.tool_registry is not None:
                    # 复制注册表，避免默认工具注册影响调用方的注册表。
                    request.tool_registry = request.tool_registry.get_copy()

                # 工具中间件在这里取得共享管理器，
                # 并将它传给 Shell 和进程工具。
                await self._init_handler(request)

                if self._llm is None or self._agent is None:
                    raise TabAgentError(
                        "Initialization middleware did not create the LLM and Agent."
                    )

                self._is_open = True
                return self

            except BaseException:
                # 初始化失败或被取消时，也需要清理已创建的资源。
                # 已经持有锁，不能调用会再次获取锁的 aclose()。
                await self._close_resources()
                raise

            finally:
                self._lifecycle_owner = None

    async def __aexit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
    ) -> None:
        await self.aclose()
