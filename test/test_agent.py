import asyncio
import os

from dotenv import load_dotenv

from tabagent.core.agent import TabAgent
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message, UserMessage
from tabagent.tool.registry import ToolRegistry


def test_agent() -> None:
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

    async def run_astream() -> None:
        async with TabAgentLLM(
                base_url=base_url,
                api_key=api_key,
        ) as llm:
            agent = TabAgent(
                llm=llm,
                model=model,
                tool_registry=tool_registry,
            )
            messages: list[Message] = []
            while True:
                human_input = await asyncio.to_thread(
                    input,
                    "Enter a request: ",
                )

                if human_input.lower() == "exit":
                    break

                if not human_input:
                    continue

                messages.append(UserMessage(human_input))

                stream = agent.astream(messages=messages)
                async for delta in stream:
                    print(delta, end="", flush=True)

                print()

    asyncio.run(run_astream())
