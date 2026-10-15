import asyncio
import inspect
import json
from copy import deepcopy
from typing import Optional, List, AsyncGenerator, Callable, Any

from openai.types.responses import Response, ResponseFunctionToolCall

from tabagent.core.exceptions import (
    AgentConfigError,
    ModelCallLimitError,
    ModelResponseFailedError,
    ModelResponseIncompleteError,
    ModelStreamError,
    ToolArgumentsError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolResultSerializationError,
)
from tabagent.core.llm import TabAgentLLM
from tabagent.core.message import Message, AssistantMessage, ToolMessage
from tabagent.core.response import (
    RESPONSE_COMPLETED,
    RESPONSE_OUTPUT_TEXT_DELTA,
    RESPONSE_FAILED,
    RESPONSE_INCOMPLETE,
    ERROR,
)
from tabagent.tool.registry import ToolRegistry


async def _execute_tool(
        call: ResponseFunctionToolCall,
        tools: dict[str, Callable[..., Any]],
) -> str:
    try:
        if call.name not in tools:
            raise ToolNotFoundError(
                f"Tool {call.name!r} is not available for this run."
            )

        try:
            arguments = json.loads(call.arguments)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ToolArgumentsError(
                f"Arguments for tool {call.name!r} are not valid JSON."
            ) from exc

        if not isinstance(arguments, dict):
            raise ToolArgumentsError(
                f"Arguments for tool {call.name!r} must decode to a JSON object."
            )

        tool = tools[call.name]
        try:
            signature = inspect.signature(tool)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError(
                f"Cannot execute tool {call.name!r}: its function signature "
                "could not be inspected."
            ) from exc

        try:
            signature.bind(**arguments)
        except TypeError as exc:
            raise ToolArgumentsError(
                f"Arguments for tool {call.name!r} do not match its function "
                "signature. Check for missing or unexpected parameters."
            ) from exc

        try:
            if inspect.iscoroutinefunction(tool):
                result = await tool(**arguments)
            else:
                result = await asyncio.to_thread(
                    tool,
                    **arguments,
                )
                if inspect.isawaitable(result):
                    result = await result
        except Exception as exc:
            raise ToolExecutionError(
                f"Tool {call.name!r} failed during execution "
                f"({type(exc).__name__})."
            ) from exc

        if isinstance(result, str):
            return result

        try:
            return json.dumps(
                result,
                ensure_ascii=False,
                allow_nan=False,
            )
        except Exception as exc:
            raise ToolResultSerializationError(
                f"Tool {call.name!r} returned a result that cannot be serialized "
                "as JSON. Return a string or a JSON-compatible value."
            ) from exc

    except ToolError as exc:
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
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise AgentConfigError("model must be a non-empty string.")
        if (
                isinstance(max_model_calls, bool)
                or not isinstance(max_model_calls, int)
                or max_model_calls < 1
        ):
            raise AgentConfigError("max_model_calls must be a positive integer.")

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
                        raise ModelResponseFailedError(
                            f"Model call {round_number} failed: the server "
                            "returned response.failed.",
                            details=event.response,
                        )
                    elif event.type == RESPONSE_INCOMPLETE:
                        raise ModelResponseIncompleteError(
                            f"Model call {round_number} ended before completion: "
                            "the server returned response.incomplete.",
                            details=event.response,
                        )
                    elif event.type == ERROR:
                        raise ModelStreamError(
                            f"Model call {round_number} reported a streaming error.",
                            details=event,
                        )
            finally:
                if inspect.isasyncgen(stream):
                    await stream.aclose()

            if response is None:
                raise ModelStreamError(
                    f"Model call {round_number} ended without a "
                    "response.completed event."
                )

            calls = [
                item
                for item in response.output
                if isinstance(item, ResponseFunctionToolCall)
            ]

            if calls and round_number == self._max_model_calls:
                raise ModelCallLimitError(
                    f"Reached the limit of {self._max_model_calls} model calls "
                    "while the model was still requesting tools. "
                    "The pending tools were not executed."
                )

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
                        message = (
                            "Tool execution was interrupted; its outcome is unknown."
                            if position == 0
                            else "Tool execution was skipped because the run was interrupted."
                        )

                        messages.append(
                            ToolMessage(
                                call_id=pending.call_id,
                                output=json.dumps({
                                    "status": status,
                                    "message": message,
                                }),
                            )
                        )
                    raise

                messages.append(
                    ToolMessage(
                        call_id=call.call_id,
                        output=output,
                    )
                )
