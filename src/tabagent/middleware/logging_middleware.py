from asyncio import CancelledError
from collections.abc import AsyncGenerator
from contextlib import aclosing
from time import perf_counter

from openai.types.responses import ResponseStreamEvent

from tabagent.core.logger import logger
from tabagent.core.response import (
    ERROR,
    RESPONSE_COMPLETED,
    RESPONSE_FAILED,
    RESPONSE_INCOMPLETE,
)
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
            await call_next(request)

        except CancelledError:
            logger.warning("App initialization cancelled.")
            raise

        except Exception:
            logger.exception("App initialization failed.")
            raise

        else:
            logger.info("App initialization completed.")

        finally:
            logger.debug(
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
                    yield delta

        except CancelledError:
            logger.warning("Agent run cancelled.")
            raise

        except GeneratorExit:
            # 调用方显式关闭尚未耗尽的异步生成器。
            logger.info("Agent stream closed before exhaustion.")
            raise

        except Exception:
            logger.exception("Agent run failed.")
            raise

        else:
            # 仅在下游流被正常读取完毕后记录完成。
            logger.info("Agent run completed.")

        finally:
            logger.debug(
                "Agent stream exited: elapsed={:.3f}s",
                perf_counter() - started_at,
            )

    async def wrap_model(
            self,
            call_next: ModelHandler,
            request: ModelRequest,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        started_at = perf_counter()

        # 记录最近收到的完成、失败、不完整或错误事件。
        outcome_event: str | None = None

        logger.info(
            "Model call started: model={}",
            request.model,
        )

        try:
            async with aclosing(call_next(request)) as stream:
                async for event in stream:
                    if event.type == RESPONSE_COMPLETED:
                        outcome_event = event.type

                        logger.info(
                            "Model response completed: "
                            "model={}, response_id={}",
                            request.model,
                            event.response.id,
                        )

                    elif event.type == RESPONSE_FAILED:
                        outcome_event = event.type
                        error = event.response.error

                        logger.error(
                            "Model response failed: "
                            "model={}, response_id={}, code={}",
                            request.model,
                            event.response.id,
                            error.code if error is not None else "unknown",
                        )

                    elif event.type == RESPONSE_INCOMPLETE:
                        outcome_event = event.type
                        details = event.response.incomplete_details

                        logger.warning(
                            "Model response incomplete: "
                            "model={}, response_id={}, reason={}",
                            request.model,
                            event.response.id,
                            (
                                details.reason
                                if details is not None
                                else "unknown"
                            ),
                        )

                    elif event.type == ERROR:
                        outcome_event = event.type

                        logger.error(
                            "Model stream reported an error: "
                            "model={}, code={}",
                            request.model,
                            event.code or "unknown",
                        )

                    # 日志记录完成后，仍将原始事件交给外层 Agent。
                    yield event

        except CancelledError:
            logger.warning(
                "Model stream cancelled: model={}",
                request.model,
            )
            raise

        except GeneratorExit:
            # Agent 遇到失败事件后也会关闭流，
            # 因此关闭本身不记为失败。
            logger.debug(
                "Model stream closed: model={}, outcome_event={}",
                request.model,
                outcome_event or "none",
            )
            raise

        except Exception:
            logger.exception(
                "Model call raised an exception: model={}",
                request.model,
            )
            raise

        else:
            # 流自然结束，却没有收到完成、失败、不完整或错误事件。
            # 此处记录异常现象；是否抛错由 Agent 决定。
            if outcome_event is None:
                logger.warning(
                    "Model stream ended without a completion "
                    "or error event: model={}",
                    request.model,
                )

        finally:
            logger.debug(
                "Model stream exited: "
                "model={}, outcome_event={}, elapsed={:.3f}s",
                request.model,
                outcome_event or "none",
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
            output = await call_next(request)

        except CancelledError:
            # 等待被取消不代表 asyncio.to_thread 中的同步工具已经停止。
            logger.warning(
                "Tool wait cancelled: name={}, call_id={}",
                request.name,
                request.call_id,
            )
            raise

        except Exception:
            logger.exception(
                "Tool execution raised an exception: "
                "name={}, call_id={}",
                request.name,
                request.call_id,
            )
            raise

        else:
            # 执行器可能返回错误 JSON；
            # 返回字符串不等于工具业务成功。
            logger.info(
                "Tool execution returned: name={}, call_id={}",
                request.name,
                request.call_id,
            )
            return output

        finally:
            logger.debug(
                "Tool execution exited: "
                "name={}, call_id={}, elapsed={:.3f}s",
                request.name,
                request.call_id,
                perf_counter() - started_at,
            )
