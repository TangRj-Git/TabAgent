import asyncio
import inspect
import json
from copy import deepcopy
from typing import Optional, List, AsyncGenerator, Callable, Any

from openai.types.responses import Response, ResponseFunctionToolCall

from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message, AssistantMessage, ToolMessage
from tabagent.core.response import (
    RESPONSE_COMPLETED,
    RESPONSE_OUTPUT_TEXT_DELTA,
    RESPONSE_FAILED,
    RESPONSE_INCOMPLETE, ERROR,
)
from tabagent.tool.registry import ToolRegistry


async def _execute_tool(
        call: ResponseFunctionToolCall,
        tools: dict[str, Callable[..., Any]],
) -> str:
    try:
        if call.name not in tools:
            raise ValueError(f"No tool called {call.name}")

        arguments = json.loads(call.arguments)
        if not isinstance(arguments, dict):
            raise ValueError("Invalid arguments")

        tool = tools[call.name]
        inspect.signature(tool).bind(**arguments)

        if inspect.iscoroutinefunction(tool):
            result = await tool(**arguments)
        else:
            result = await asyncio.to_thread(
                tool,
                **arguments,
            )
            if inspect.isawaitable(result):
                result = await result

        if isinstance(result, str):
            return result

        return json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
        )

    except Exception as exc:
        return json.dumps(
            {
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            },
            ensure_ascii=False,
        )


class TabAgent:
    def __init__(
            self,
            *,
            llm: TabAgentLLM,
            model: str,
            instructions: Optional[str] = None,
            tool_registry: Optional[ToolRegistry] = None,
            max_model_calls: int = 10,
    ):
        self._llm = llm
        self._model = model.strip()
        self._instructions = instructions
        self._tool_registry = tool_registry if tool_registry is not None else ToolRegistry()
        self._max_model_calls = max_model_calls

    async def astream(
            self,
            messages: List[Message],
    ) -> AsyncGenerator[str, None]:
        functions = deepcopy(self._tool_registry.get_functions())
        tools = self._tool_registry.get_tools()

        for round_number in range(1, self._max_model_calls + 1):
            response: Optional[Response] = None

            stream = self._llm.astream(
                model=self._model,
                instructions=self._instructions,
                messages=messages,
                functions=functions
            )

            try:
                async for event in stream:
                    if event.type == RESPONSE_OUTPUT_TEXT_DELTA:
                        yield event.delta
                    elif event.type == RESPONSE_COMPLETED:
                        response = event.response
                    elif event.type == RESPONSE_FAILED:
                        raise RuntimeError(f"Failed to execute tool {round_number}")
                    elif event.type == RESPONSE_INCOMPLETE:
                        raise RuntimeError(f"Failed to execute tool {round_number}")
                    elif event.type == ERROR:
                        raise RuntimeError(f"Failed to execute tool {round_number}")
            finally:
                if inspect.isasyncgen(stream):
                    await stream.aclose()

            if response is None:
                raise RuntimeError(f"No response received for round {round_number}")

            calls = [
                item
                for item in response.output
                if isinstance(item, ResponseFunctionToolCall)
            ]

            if calls and round_number == self._max_model_calls:
                raise RuntimeError("Max model calls reached")

            messages.extend(
                AssistantMessage(item)
                for item in response.output
            )

            if not calls:
                return

            for index, call in enumerate(calls):
                try:
                    output = await _execute_tool(call, tools)

                except BaseException:
                    for position, pending in enumerate(calls[index:]):
                        status = (
                            "interrupted_unknown"
                            if position == 0
                            else "not_executed"
                        )

                        messages.append(
                            ToolMessage(
                                call_id=pending.call_id,
                                output=json.dumps({"status": status}),
                            )
                        )
                    raise

                messages.append(
                    ToolMessage(
                        call_id=call.call_id,
                        output=output,
                    )
                )
