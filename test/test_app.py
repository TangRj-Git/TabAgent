import asyncio
import os
from contextlib import aclosing
from typing import AsyncGenerator

from dotenv import load_dotenv

from openai.types.responses import ResponseStreamEvent

from tabagent.core.app import TabAgentApp
from tabagent.core.message import UserMessage, Message
from tabagent.middleware.base_middleware import BaseMiddleware, AppInitHandler, AppInitRequest, AgentHandler, \
    AgentRequest, ModelHandler, ModelRequest, ToolHandler, ToolRequest
from tabagent.tool.registry import ToolRegistry


def add(a: float, b: float) -> float:
    """计算 a 加 b。"""
    return a + b


def multiply(a: float, b: float) -> float:
    """计算 a 乘 b。"""
    return a * b


class TimeoutMiddleware(BaseMiddleware):
    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        print("Timeout middleware: before initialization.")

        # 修改初始化配置，随后用于创建 LLM 客户端。
        request.timeout = 120.0

        await call_next(request)

        print("Timeout middleware: after initialization.")

    async def wrap_agent(
            self,
            call_next: AgentHandler,
            request: AgentRequest,
    ) -> AsyncGenerator[str, None]:
        print("Timeout middleware: before agent execution.")

        try:
            # 下一层返回异步生成器，逐段向外传递文本。
            async with aclosing(call_next(request)) as stream:
                async for delta in stream:
                    yield delta

        finally:
            # 正常结束、异常或生成器关闭时执行。
            print("Timeout middleware: agent stream exited.")

    async def wrap_model(
            self,
            call_next: ModelHandler,
            request: ModelRequest,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        print("Timeout middleware: before model execution.")

        try:
            # 下一层返回异步生成器，逐个向外传递模型事件。
            async with aclosing(call_next(request)) as stream:
                async for event in stream:
                    yield event

        finally:
            print("Timeout middleware: model stream exited.")

    async def wrap_tool(
            self,
            call_next: ToolHandler,
            request: ToolRequest,
    ) -> str:
        print(
            f"Timeout middleware: before tool execution: "
            f"name={request.name}"
        )

        try:
            # 工具返回单个结果，需要等待并将结果交回上一层。
            output = await call_next(request)
            return output

        finally:
            print(
                f"Timeout middleware: tool execution exited: "
                f"name={request.name}"
            )


class InitLoggingMiddleware(BaseMiddleware):
    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        print(
            f"Initialization started: "
            f"timeout={request.timeout}"
        )

        await call_next(request)

        print("Initialization completed.")

    async def wrap_agent(
            self,
            call_next: AgentHandler,
            request: AgentRequest,
    ) -> AsyncGenerator[str, None]:
        print(
            f"Agent execution started: "
            f"model={request.model}, "
            f"max_model_calls={request.max_model_calls}"
        )

        try:
            async with aclosing(call_next(request)) as stream:
                async for delta in stream:
                    yield delta

        finally:
            print("Agent stream exited.")

    async def wrap_model(
            self,
            call_next: ModelHandler,
            request: ModelRequest,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        print(
            f"Model execution started: "
            f"model={request.model}, "
            f"function_count={len(request.functions)}"
        )

        try:
            async with aclosing(call_next(request)) as stream:
                async for event in stream:
                    yield event

        finally:
            print("Model stream exited.")

    async def wrap_tool(
            self,
            call_next: ToolHandler,
            request: ToolRequest,
    ) -> str:
        print(
            f"Tool execution started: "
            f"name={request.name}, "
            f"call_id={request.call_id}"
        )

        try:
            output = await call_next(request)
            return output

        finally:
            print(
                f"Tool execution exited: "
                f"name={request.name}, "
                f"call_id={request.call_id}"
            )


def test_app() -> None:
    load_dotenv()

    base_url = os.getenv('OPENAI_BASE_URL')
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL')

    tool_registry = ToolRegistry()
    tool_registry.register_tool(add)
    tool_registry.register_tool(multiply)

    messages: list[Message] = [
        UserMessage("请使用工具计算 12 加 8，然后乘 4。"),
    ]

    async def run() -> None:
        async with TabAgentApp(
                base_url=base_url,
                api_key=api_key,
                model=model,
                instructions="Use the available tools for arithmetic.",
                tool_registry=tool_registry,
        ) as app:
            async with aclosing(app.astream(messages)) as stream:
                async for delta in stream:
                    print(delta, end="", flush=True)
            print()

    asyncio.run(run())


def test_app_with_middleware() -> None:
    load_dotenv()

    base_url = os.getenv('OPENAI_BASE_URL')
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL')

    tool_registry = ToolRegistry()
    tool_registry.register_tool(add)
    tool_registry.register_tool(multiply)

    timeout_middleware = TimeoutMiddleware()
    init_logging_middleware = InitLoggingMiddleware()

    middlewares = (timeout_middleware, init_logging_middleware)

    messages: list[Message] = [
        UserMessage("请使用工具计算 12 加 8，然后乘 4。"),
    ]

    async def run() -> None:
        async with TabAgentApp(
                base_url=base_url,
                api_key=api_key,
                model=model,
                instructions="Use the available tools for arithmetic.",
                tool_registry=tool_registry,
                middlewares=middlewares,
        ) as app:
            async with aclosing(app.astream(messages=messages)) as stream:
                async for delta in stream:
                    print(delta, end="", flush=True)
                print()

    asyncio.run(run())
