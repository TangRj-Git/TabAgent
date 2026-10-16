from collections.abc import AsyncGenerator
from contextlib import aclosing
from time import perf_counter

from openai.types.responses import ResponseStreamEvent

from tabagent.core.logger import logger
from tabagent.middleware.base_middleware import (
    AgentHandler,
    AgentRequest,
    AppInitHandler,
    AppInitRequest,
    BaseMiddleware,
    ModelHandler,
    ModelRequest,
    ToolHandler,
    ToolRequest,
)


class LoggingMiddleware(BaseMiddleware):
    """记录初始化、Agent 运行、模型调用和工具执行的日志。"""

    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        started_at = perf_counter()

        logger.info(
            "App initialization started: model={}",
            request.model,
        )

        try:
            # 执行下一层，最终创建 LLM 和 Agent。
            await call_next(request)

        except Exception:
            logger.exception("App initialization failed.")
            raise

        else:
            logger.info("App initialization completed.")

        finally:
            logger.info(
                "App initialization exited: elapsed={:.3f}s",
                perf_counter() - started_at,
            )

    async def wrap_agent(
            self,
            call_next: AgentHandler,
            request: AgentRequest,
    ) -> AsyncGenerator[str, None]:
        started_at = perf_counter()

        logger.info(
            "Agent run started: model={}, message_count={}",
            request.model,
            len(request.messages),
        )

        try:
            async with aclosing(call_next(request)) as stream:
                async for delta in stream:
                    # 原样向调用方传递文本增量。
                    yield delta

        except Exception:
            logger.exception("Agent run failed.")
            raise

        else:
            # 只有流被正常读取完毕，才记录完成。
            logger.info("Agent run completed.")

        finally:
            # 正常结束、异常、取消或显式关闭流时都会执行。
            logger.info(
                "Agent stream exited: elapsed={:.3f}s",
                perf_counter() - started_at,
            )

    async def wrap_model(
            self,
            call_next: ModelHandler,
            request: ModelRequest,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        started_at = perf_counter()

        logger.info(
            "Model call started: model={}",
            request.model,
        )

        try:
            async with aclosing(call_next(request)) as stream:
                async for event in stream:
                    # 模型失败可能通过事件报告，因此需要检查事件类型。
                    if event.type == "response.completed":
                        logger.info(
                            "Model response completed: response_id={}",
                            event.response.id,
                        )

                    elif event.type == "response.failed":
                        logger.error("Model response failed.")

                    elif event.type == "response.incomplete":
                        logger.warning("Model response is incomplete.")

                    elif event.type == "error":
                        logger.error("Model stream reported an error.")

                    # 所有事件仍然交给外层处理。
                    yield event

        except Exception:
            logger.exception(
                "Model call raised an exception: model={}",
                request.model,
            )
            raise

        finally:
            logger.info(
                "Model stream exited: model={}, elapsed={:.3f}s",
                request.model,
                perf_counter() - started_at,
            )

    async def wrap_tool(
            self,
            call_next: ToolHandler,
            request: ToolRequest,
    ) -> str:
        started_at = perf_counter()

        logger.info(
            "Tool execution started: name={}, call_id={}",
            request.name,
            request.call_id,
        )

        try:
            # 执行下一层，获取工具结果字符串。
            output = await call_next(request)

        except Exception:
            logger.exception(
                "Tool execution raised an exception: name={}, call_id={}",
                request.name,
                request.call_id,
            )
            raise

        else:
            # 返回值可能包含错误 JSON，因此这里只记录 returned。
            logger.info(
                "Tool execution returned: name={}, call_id={}",
                request.name,
                request.call_id,
            )

            return output

        finally:
            logger.info(
                "Tool execution exited: name={}, call_id={}, elapsed={:.3f}s",
                request.name,
                request.call_id,
                perf_counter() - started_at,
            )
