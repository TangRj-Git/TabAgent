import asyncio
import os
from contextlib import aclosing

from dotenv import load_dotenv

from tabagent.core.app import TabAgentApp
from tabagent.core.message import UserMessage, Message
from tabagent.middleware.base_middleware import BaseMiddleware, AppInitHandler, AppInitRequest
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

        # 修改本次初始化使用的参数。
        request.timeout = 120.0

        # 进入下一层。
        await call_next(request)

        print("Timeout middleware: after initialization.")


class InitLoggingMiddleware(BaseMiddleware):
    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        print(f"Initialization started: timeout={request.timeout}")

        # 进入下一层。
        await call_next(request)

        print("Initialization completed.")


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
