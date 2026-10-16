from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from openai.types.responses import ResponseStreamEvent

from tabagent.core.function import Function
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message
from tabagent.tool.registry import ToolRegistry


@dataclass
class AppInitRequest:
    """
    TabAgentApp 创建 LLM 和 Agent 时使用的配置。

    初始化中间件可以在对象创建之前修改这些参数。
    """

    base_url: str
    api_key: str = field(repr=False)

    model: str
    instructions: str | None = None
    tool_registry: ToolRegistry | None = None
    max_model_calls: int = 10

    timeout: float | None = 60.0
    max_retries: int = 3


@dataclass
class AgentRequest:
    """
    一次完整 Agent 运行使用的参数。

    每次运行时创建，初始值来自 Agent 的默认配置。
    中间件可以覆盖本次运行使用的配置。
    """

    # 本次运行使用的消息历史。
    messages: list[Message]

    # 本次运行使用的、已经初始化好的 LLM 客户端。
    llm: TabAgentLLM

    # 本次运行使用的模型。
    model: str

    # 本次运行使用的工具注册表。
    tool_registry: ToolRegistry

    instructions: str | None = None
    max_model_calls: int = 10


@dataclass
class ModelRequest:
    """单次模型调用使用的参数。"""

    messages: list[Message]
    model: str
    instructions: str | None = None
    functions: list[Function] = field(default_factory=list)


@dataclass
class ToolRequest:
    """单次工具执行使用的参数。"""

    # 用于关联模型发出的工具调用，执行过程中应保持不变。
    call_id: str

    name: str

    # 已从 JSON 字符串解析出的参数字典。
    arguments: dict[str, Any]


# 初始化执行函数：
# 根据配置创建 LLM 和 Agent，并由 TabAgentApp 保存和管理。
AppInitHandler: TypeAlias = Callable[
    [AppInitRequest],
    Awaitable[None],
]

# Agent 执行函数：
# 返回逐段输出文本的异步生成器。
AgentHandler: TypeAlias = Callable[
    [AgentRequest],
    AsyncGenerator[str, None],
]

# 模型执行函数：
# 返回逐个输出模型事件的异步生成器。
ModelHandler: TypeAlias = Callable[
    [ModelRequest],
    AsyncGenerator[ResponseStreamEvent, None],
]

# 工具执行函数：
# 返回工具结果字符串。
ToolHandler: TypeAlias = Callable[
    [ToolRequest],
    Awaitable[str],
]


class BaseMiddleware:
    """
    中间件基类。

    提供初始化、Agent 执行、模型调用和工具执行四个包装入口。

    默认将请求交给下一层，并原样传递结果。
    子类可以按需重写其中任意方法。
    """

    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        """
        包装 TabAgentApp 创建 LLM 和 Agent 的过程。

        调用下一层之前，可以检查或修改初始化配置。
        下一层返回之后，可以执行初始化后的处理。

        已创建资源的保存和清理由 TabAgentApp 负责。
        """

        # 定义这个方法或创建 partial 时，不会执行到这里。
        # 真正执行 await 外层handler(request) 后，才会进入这个方法。
        #
        # 运行到下面这一行时，会调用下一层并等待它完成。
        # 下一层可能是另一个中间件，也可能是最终的 _initialize。
        #
        # 默认实现不修改 request，只将同一个请求对象交给下一层。
        await call_next(request)

    async def wrap_agent(
            self,
            call_next: AgentHandler,
            request: AgentRequest,
    ) -> AsyncGenerator[str, None]:
        """
        包装一次完整的 Agent 运行。

        调用下一层之前，可以修改本次运行参数。
        读取流时，可以处理向外输出的文本增量。
        """
        async with aclosing(call_next(request)) as stream:
            async for delta in stream:
                yield delta

    async def wrap_model(
            self,
            call_next: ModelHandler,
            request: ModelRequest,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        """
        包装单次模型调用。

        调用下一层之前，可以修改模型、提示词、消息和函数定义。
        读取流时，可以检查或处理模型事件。
        """
        async with aclosing(call_next(request)) as stream:
            async for event in stream:
                yield event

    async def wrap_tool(
            self,
            call_next: ToolHandler,
            request: ToolRequest,
    ) -> str:
        """
        包装单次工具执行。

        调用下一层之前，可以检查或修改工具参数。
        下一层返回之后，可以处理工具结果。
        """
        return await call_next(request)
