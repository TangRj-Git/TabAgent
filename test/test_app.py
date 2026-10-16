import asyncio
import os
from contextlib import aclosing

from dotenv import load_dotenv

from tabagent.core.app import TabAgentApp
from tabagent.core.message import UserMessage, Message
from tabagent.tool.registry import ToolRegistry


def test_app() -> None:
    load_dotenv()

    base_url = os.getenv('OPENAI_BASE_URL')
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL')

    def add(a: float, b: float) -> float:
        """计算 a 加 b。"""
        return a + b

    def multiply(a: float, b: float) -> float:
        """计算 a 乘 b。"""
        return a * b

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
