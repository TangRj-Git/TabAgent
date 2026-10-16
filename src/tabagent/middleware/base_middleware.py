from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from openai.types.responses import ResponseStreamEvent

from tabagent.core.function import Function
from tabagent.core.message import Message


@dataclass
class AgentRequest:
    """一次完整 Agent 运行使用的参数。"""

    messages: list[Message]
    model: str
    instructions: str | None = None
    max_model_calls: int = 10

    # None：允许使用所有已注册工具。
    # 空集合：本次运行禁用工具。
    allowed_tools: set[str] | None = None


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


# Agent 和模型返回异步生成器，支持逐段读取和 aclose()。
AgentHandler: TypeAlias = Callable[
    [AgentRequest],
    AsyncGenerator[str, None],
]

ModelHandler: TypeAlias = Callable[
    [ModelRequest],
    AsyncGenerator[ResponseStreamEvent, None],
]

# 工具返回单个结果，沿用当前项目的字符串结果格式。
ToolHandler: TypeAlias = Callable[
    [ToolRequest],
    Awaitable[str],
]


class BaseMiddleware:
    """
    中间件基类。

    默认将请求交给下一层，并原样返回结果。
    子类可以重写任意包装方法，在执行前后增加处理。
    """

    async def wrap_agent(
            self,
            call_next: AgentHandler,
            request: AgentRequest,
    ) -> AsyncGenerator[str, None]:
        """包装一次完整的 Agent 流式执行。"""

        async with aclosing(call_next(request)) as stream:
            async for delta in stream:
                yield delta

    async def wrap_model(
            self,
            call_next: ModelHandler,
            request: ModelRequest,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        """包装单次模型流式调用。"""

        async with aclosing(call_next(request)) as stream:
            async for event in stream:
                yield event

    async def wrap_tool(
            self,
            call_next: ToolHandler,
            request: ToolRequest,
    ) -> str:
        """包装单次工具执行。"""

        return await call_next(request)
