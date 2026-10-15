import asyncio
import json
import os
from typing import Optional

from dotenv import load_dotenv
from openai.types.responses import Response

from tabagent.core.function import Function
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import UserMessage, AssistantMessage, Message, ToolMessage
from tabagent.tool.registry import ToolRegistry


def test_llm() -> None:
    load_dotenv()

    base_url = os.getenv('OPENAI_BASE_URL')
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL')

    async def run_astream() -> None:
        async with TabAgentLLM(
                base_url=base_url,
                api_key=api_key,
        ) as llm:
            async for event in llm.astream(
                    model=model,
                    instructions="请用中文简短回答。",
                    messages=[UserMessage("用一句话介绍 Python。")],
                    functions=[],
            ):
                print(event)

    asyncio.run(run_astream())


def test_llm_with_tools() -> None:
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
                base_url=base_url,
                api_key=api_key,
        ) as llm:
            for round_number in range(1, 5):
                response: Optional[Response] = None

                # 先完整读取本轮流式响应。
                async for event in llm.astream(
                        model=model,
                        instructions="涉及算术时使用提供的函数；得到最终结果后用中文回答。",
                        messages=history,  # 必须包含之前的函数调用和执行结果。
                        functions=tools_function,
                ):
                    print(event)

                    if event.type == "response.completed":
                        response = event.response

                # 没有成功完成事件，就不继续执行函数或提交本轮历史。
                if response is None:
                    raise RuntimeError(f"第 {round_number} 轮未成功完成")

                # 保存完整输出，包括推理项、函数调用和文本消息。
                history.extend(
                    AssistantMessage(item)
                    for item in response.output
                )

                calls = [
                    item
                    for item in response.output
                    if item.type == "function_call"
                ]

                # 没有待执行的函数调用，结束整个异步函数。
                if not calls:
                    return

                # 执行函数，并将结果放入下一轮请求的历史中。
                for call in calls:
                    arguments = json.loads(call.arguments)
                    result = functions[call.name](**arguments)

                    history.append(
                        ToolMessage(
                            call_id=call.call_id,
                            output=json.dumps(result),
                        )
                    )

                print("=" * 50)

            raise RuntimeError("已达到 4 轮调用上限，模型仍在请求调用函数")

    asyncio.run(run_astream())


def test_llm_with_register() -> None:
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

    history: list[Message] = [UserMessage("先用工具算 12 乘 3，再用工具给结果加 8。")]

    async def run_astream() -> None:
        async with TabAgentLLM(
                base_url=base_url,
                api_key=api_key,
        ) as llm:
            for round_number in range(1, 5):
                response: Optional[Response] = None

                # 先完整读取本轮流式响应。
                async for event in llm.astream(
                        model=model,
                        instructions="涉及算术时使用提供的函数；得到最终结果后用中文回答。",
                        messages=history,
                        functions=tool_registry.get_functions(),
                ):
                    print(event)

                    if event.type == "response.completed":
                        response = event.response

                # 没有成功完成事件，就不继续执行函数或提交本轮历史。
                if response is None:
                    raise RuntimeError(f"第 {round_number} 轮未成功完成")

                # 保存完整输出，包括推理项、函数调用和文本消息。
                history.extend(
                    AssistantMessage(item)
                    for item in response.output
                )

                calls = [
                    item
                    for item in response.output
                    if item.type == "function_call"
                ]

                # 没有待执行的函数调用，结束整个异步函数。
                if not calls:
                    return

                # 执行函数，并将结果放入下一轮请求的历史中。
                for call in calls:
                    arguments = json.loads(call.arguments)
                    result = tool_registry.get_tool(call.name)(**arguments)

                    history.append(
                        ToolMessage(
                            call_id=call.call_id,
                            output=json.dumps(result),
                        )
                    )

                print("=" * 50)

            raise RuntimeError("已达到 4 轮调用上限，模型仍在请求调用函数")

    asyncio.run(run_astream())


def test_llm_with_input() -> None:
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
        history: list[Message] = []

        async with TabAgentLLM(
                base_url=base_url,
                api_key=api_key,
        ) as llm:
            while True:
                # 在线程中等待终端输入，避免阻塞事件循环。
                # pytest 默认开启输出捕获，并禁止 input() 读取标准输入。
                # -s 会关闭 pytest 的捕获，让你能够在终端输入请求。
                human_input = await asyncio.to_thread(
                    input,
                    "请输入请求：",
                )
                human_input = human_input.strip()

                if human_input.lower() == "exit":
                    break

                if not human_input:
                    continue

                history.append(UserMessage(human_input))

                for round_number in range(1, 5):
                    response: Optional[Response] = None

                    # 先完整读取本轮流式响应。
                    async for event in llm.astream(
                            model=model,
                            instructions="涉及算术时使用提供的函数；得到最终结果后用中文回答。",
                            messages=history,
                            functions=tool_registry.get_functions(),
                    ):
                        print(event)

                        if event.type == "response.completed":
                            response = event.response

                    print(response.output_text)

                    # 没有成功完成事件，就不继续执行函数或提交本轮历史。
                    if response is None:
                        raise RuntimeError(f"第 {round_number} 轮未成功完成")

                    # 保存完整输出，包括推理项、函数调用和文本消息。
                    history.extend(
                        AssistantMessage(item)
                        for item in response.output
                    )

                    calls = [
                        item
                        for item in response.output
                        if item.type == "function_call"
                    ]

                    # 没有待执行的函数调用，结束整个异步函数。
                    if not calls:
                        break

                    # 执行函数，并将结果放入下一轮请求的历史中。
                    for call in calls:
                        arguments = json.loads(call.arguments)
                        result = tool_registry.get_tool(call.name)(**arguments)

                        history.append(
                            ToolMessage(
                                call_id=call.call_id,
                                output=json.dumps(
                                    result,
                                    ensure_ascii=False,
                                ),
                            )
                        )

                    print("=" * 50)
                else:
                    raise RuntimeError("已达到 4 轮调用上限，模型仍在请求调用函数")

    asyncio.run(run_astream())
