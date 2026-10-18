from contextlib import aclosing
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Optional, Self, AsyncGenerator, Sequence

from tabagent.core.agent import TabAgent
from tabagent.core.exceptions import TabAgentError
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message
from tabagent.core.middleware import MiddlewareManager
from tabagent.middleware.base_middleware import BaseMiddleware, AppInitRequest
from tabagent.tool.registry import ToolRegistry


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

        self._opening = False

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

        if agent is None:
            raise TabAgentError(
                "TabAgentApp is not open. "
                "Use 'async with TabAgentApp(...)' before streaming."
            )

        # aclosing() 的作用，就是把生成器包装成可用于 async with 的对象，并在退出时调用它的 aclose()。
        # 异步生成器对象自带 aclose() 方法，由 Python 提供，不需要你自己实现。
        async with aclosing(agent.astream(messages=messages)) as stream:
            async for delta in stream:
                yield delta

    async def aclose(self) -> None:
        """关闭内部创建的 LLM 客户端，允许重复调用。"""

        llm = self._llm

        self._agent = None
        self._llm = None

        if llm is not None:
            await llm.aclose()

    async def __aenter__(self) -> Self:
        """创建本实例拥有的 LLM 和 Agent。"""

        if self._opening or self._llm is not None:
            raise TabAgentError("TabAgentApp is already open.")

        self._opening = True

        try:
            # 创建本次初始化的配置，保留原始默认配置。
            request = replace(self._config)

            # 未配置工具注册表时，保持 None。
            if request.tool_registry is not None:
                # 为本次请求创建独立的工具注册表副本。
                # 后续中间件可以在副本中动态注册或删除工具，
                # 避免影响 Agent 的默认注册表以及其他请求。
                # 已有工具定义的内部字段是否也被复制，取决于 get_copy() 的实现。
                request.tool_registry = request.tool_registry.get_copy()

            # 初始化中间件接收并操作这里传入的 AppInitRequest 对象 request。
            # 中间件可以在 await call_next(request) 之前修改 request 的字段，然后将修改后的 request 继续传给下一层。
            # 最终 _initialize(request) 使用这些参数创建 LLM 和 Agent。
            # 对象创建后，再修改 request 不会自动更新已经创建的对象。
            await self._init_handler(request)

            if self._llm is None or self._agent is None:
                raise TabAgentError(
                    "Initialization middleware did not create the LLM and Agent."
                )
        except BaseException:
            await self.aclose()
            raise

        finally:
            self._opening = False

        return self

    async def __aexit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
    ) -> None:
        await self.aclose()
