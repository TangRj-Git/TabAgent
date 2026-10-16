from contextlib import aclosing
from types import TracebackType
from typing import Optional, Self, AsyncGenerator

from tabagent.core.agent import TabAgent
from tabagent.core.exceptions import TabAgentError
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message
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

            # Agent 配置。
            model: str,
            instructions: Optional[str] = None,
            tool_registry: Optional[ToolRegistry] = None,
            max_model_calls: int = 10,

            # LLM 请求配置。
            timeout: Optional[float] = 60.0,
            max_retries: int = 3,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries

        self._model = model
        self._instructions = instructions
        self._tool_registry = tool_registry
        self._max_model_calls = max_model_calls

        # 进入异步上下文后才创建。
        self._llm: Optional[TabAgentLLM] = None
        self._agent: Optional[TabAgent] = None

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

        if self._llm is not None:
            raise TabAgentError("TabAgentApp is already open.")

        llm = TabAgentLLM(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

        try:
            agent = TabAgent(
                llm=llm,
                model=self._model,
                instructions=self._instructions,
                tool_registry=self._tool_registry,
                max_model_calls=self._max_model_calls,
            )

        except BaseException:
            # Agent 创建失败时，关闭已经创建的 LLM 客户端。
            await llm.aclose()
            raise

        self._llm = llm
        self._agent = agent

        return self

    async def __aexit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
    ) -> None:
        await self.aclose()
