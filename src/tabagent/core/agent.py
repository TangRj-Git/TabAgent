import asyncio
import inspect
import json
from contextlib import aclosing
from copy import deepcopy
from functools import partial
from typing import Optional, List, AsyncGenerator, Callable, Any

from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseStreamEvent,
)

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
from tabagent.core.middleware import MiddlewareManager
from tabagent.core.response import (
    RESPONSE_COMPLETED,
    RESPONSE_OUTPUT_TEXT_DELTA,
    RESPONSE_FAILED,
    RESPONSE_INCOMPLETE,
    ERROR,
    RESPONSE_REFUSAL_DELTA,
)
from tabagent.middleware.base_middleware import AgentRequest, ModelRequest, ToolRequest
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
        except ToolError:
            # 保留工具已经明确分类的异常。
            # 交给外层 except ToolError 转换成错误 JSON。
            raise
        except Exception as exc:
            # 尚未分类的普通异常，统一包装为工具执行错误。
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
            middleware_manager: Optional[MiddlewareManager] = None
    ) -> None:
        self._validate_config(model, max_model_calls)

        self._llm = llm
        self._model = model.strip()
        self._instructions = instructions
        self._tool_registry = tool_registry if tool_registry is not None else ToolRegistry()
        self._max_model_calls = max_model_calls

        self._middleware_manager = middleware_manager if middleware_manager is not None else MiddlewareManager()

        # 将 Agent 执行函数放在中间件链的最内层。
        # _run_agent 是实际执行 Agent 的方法，_agent_handler 是包装中间件后的调用入口。
        # 没有中间件时，直接使用 _run_agent；这里只组装调用链，不执行。
        self._agent_handler = self._middleware_manager.build_agent(self._run_agent)

    @staticmethod
    def _validate_config(
            model: str,
            max_model_calls: int,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise AgentConfigError(
                "model must be a non-empty string."
            )

        if (
                isinstance(max_model_calls, bool)
                or not isinstance(max_model_calls, int)
                or max_model_calls < 1
        ):
            raise AgentConfigError(
                "max_model_calls must be a positive integer."
            )

    @staticmethod
    async def _call_model(
            llm: TabAgentLLM,
            request: ModelRequest,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        """模型中间件链最内层：真正调用 LLM。"""
        async with aclosing(
                llm.astream(
                    model=request.model,
                    instructions=request.instructions,
                    messages=request.messages,
                    functions=request.functions,
                )
        ) as stream:
            async for event in stream:
                yield event

    async def _run_agent(
            self,
            request: AgentRequest,
    ) -> AsyncGenerator[str, None]:
        # 检查经过 Agent 中间件修改后的配置。
        self._validate_config(
            request.model,
            request.max_model_calls,
        )

        functions = deepcopy(request.tool_registry.get_functions())
        tools = request.tool_registry.get_tools()

        # 当前 ModelRequest 没有 llm 字段，
        # 将本次运行选定的客户端绑定到终端处理函数。
        model_handler = self._middleware_manager.build_model(
            partial(self._call_model, request.llm)
        )

        for round_number in range(1, request.max_model_calls + 1):
            response: Optional[Response] = None

            # 模型中间件拿到独立副本。
            # 临时修改上下文或函数定义，不会直接改动原始历史和注册表。
            model_request = ModelRequest(
                messages=deepcopy(request.messages),
                model=request.model,
                instructions=request.instructions,
                functions=deepcopy(functions),
            )

            async with aclosing(model_handler(model_request)) as stream:
                try:
                    async for event in stream:
                        if event.type == RESPONSE_OUTPUT_TEXT_DELTA:
                            yield event.delta
                        elif event.type == RESPONSE_REFUSAL_DELTA:
                            yield event.delta
                        elif event.type == RESPONSE_COMPLETED:
                            response = event.response
                        elif event.type == RESPONSE_FAILED:
                            raise ModelResponseFailedError(
                                f"Model call {round_number} failed: "
                                "the server returned response.failed.",
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

                if calls and round_number == request.max_model_calls:
                    raise ModelCallLimitError(
                        f"Reached the limit of {request.max_model_calls} model calls "
                        "while the model was still requesting tools. "
                        "The pending tools were not executed."
                    )

                request.messages.extend(
                    AssistantMessage(item)
                    for item in response.output
                )

                if not calls:
                    return

                for index, call in enumerate(calls):
                    try:
                        output = await self._call_tool(call, tools)

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

                            request.messages.append(
                                ToolMessage(
                                    call_id=pending.call_id,
                                    output=json.dumps({
                                        "status": status,
                                        "message": message,
                                    }),
                                )
                            )
                        raise

                    request.messages.append(
                        ToolMessage(
                            call_id=call.call_id,
                            output=output,
                        )
                    )

    async def astream(
            self,
            messages: List[Message],
    ) -> AsyncGenerator[str, None]:
        request = AgentRequest(
            messages=messages,
            llm=self._llm,
            model=self._model,
            tool_registry=self._tool_registry.get_copy(),
            instructions=self._instructions,
            max_model_calls=self._max_model_calls,
        )

        async with aclosing(self._agent_handler(request)) as stream:
            async for delta in stream:
                yield delta

    async def _call_tool(
            self,
            call: ResponseFunctionToolCall,
            tools: dict[str, Callable[..., Any]],
    ) -> str:
        """解析调用，经过工具中间件，再交给已有执行器。"""
        try:
            try:
                # JSON 字符串 → Python 字典
                arguments = json.loads(call.arguments)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ToolArgumentsError(
                    f"Arguments for tool {call.name!r} are not valid JSON."
                ) from exc

            if not isinstance(arguments, dict):
                raise ToolArgumentsError(
                    f"Arguments for tool {call.name!r} must decode to a JSON object."
                )

            # id 标识这条函数调用输出项；call_id 用来把函数调用和它的执行结果关联起来。
            request = ToolRequest(
                call_id=call.call_id,
                name=call.name,
                arguments=arguments,
            )

            async def execute(request: ToolRequest) -> str:
                if request.call_id != call.call_id:
                    raise ToolArgumentsError(
                        "Tool middleware must not change call_id."
                    )

                if not isinstance(request.arguments, dict):
                    raise ToolArgumentsError(
                        "Tool arguments must be a dictionary."
                    )

                try:
                    # Python 字典 → JSON 字符串
                    encoded_arguments = json.dumps(
                        request.arguments,
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ToolArgumentsError(
                        "Tool arguments must be JSON-compatible."
                    ) from exc

                # 将修改后的名称和参数交给已有执行器。
                # 使用副本，保留历史中的原始调用项。
                effective_call = call.model_copy(
                    update={
                        "name": request.name,
                        "arguments": encoded_arguments,
                    }
                )

                return await _execute_tool(
                    effective_call,
                    tools,
                )

            # 倒序遍历中间件，通过 partial 将下一层 handler 绑定为当前中间件的 call_next。
            # 此时只构建调用链，不执行中间件或 terminal，也不处理 request。
            # 例如注册顺序为 [A, B]，构建结果为 A(B(terminal))，返回最外层入口。
            # 执行 await handler(request) 时，才按注册顺序进入各层中间件。
            # 若每层都调用 await call_next(request) 并正常返回，执行顺序为：
            # A 前置逻辑 → B 前置逻辑 → terminal → B 后置逻辑 → A 后置逻辑。
            handler = self._middleware_manager.build_tool(execute)
            output = await handler(request)

            if not isinstance(output, str):
                raise ToolResultSerializationError(
                    "Tool middleware must return a string."
                )

            return output

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
