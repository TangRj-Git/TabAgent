import asyncio
import os

from dotenv import load_dotenv

from tabagent.core.function import Function
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import UserMessage, AssistantMessage, Message


def test_llm() -> None:
    load_dotenv()

    provider = os.getenv('OPENAI_PROVIDER')
    base_url = os.getenv('OPENAI_BASE_URL')
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL')

    async def run_astream() -> None:
        async with TabAgentLLM(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
        ) as llm:
            async for event in llm.astream(
                    model=model,
                    instructions="请用中文简短回答。",
                    messages=[UserMessage("用一句话介绍 Python。")],
                    tools=[],
            ):
                print(event)

    asyncio.run(run_astream())


def test_llm_with_tools() -> None:
    load_dotenv()

    provider = os.getenv('OPENAI_PROVIDER')
    base_url = os.getenv('OPENAI_BASE_URL')
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL')

    def add(a: float, b: float) -> float:
        """计算 a 加 b。"""
        return a + b

    def multiply(a: float, b: float) -> float:
        """计算 a 乘 b。"""
        return a * b

    functions = {"add": add, "multiply": multiply}

    add_function = Function(
        name=add.__name__,
        description=add.__doc__,
        parameters={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    )
    multiply_function = Function(
        name=multiply.__name__,
        description=multiply.__doc__,
        parameters={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        }
    )
    tools_function = [add_function, multiply_function]

    history: list[Message] = [UserMessage("先用工具算 12 乘 3，再用工具给结果加 8。")]

    async def run_astream() -> None:
        async with TabAgentLLM(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
        ) as llm:
            async for event in llm.astream(
                    model=model,
                    instructions="涉及算术时使用提供的函数；得到最终结果后用中文回答。",
                    messages=[UserMessage("先用工具算 12 乘 3，再用工具给结果加 8。")],
                    tools=tools_function,
            ):
                print(event)
                if event.type == "response.completed":
                    history.extend(
                        AssistantMessage(item)
                        for item in event.response.output
                    )

    asyncio.run(run_astream())
