from contextlib import aclosing
from functools import partial

from tabagent.core.logger import logger


class BaseMiddleware:
    async def wrap_model(self, call_next, **request):
        """默认行为：将请求交给下一层，原样传出事件。"""

        async with aclosing(call_next(**request)) as stream:
            async for event in stream:
                yield event


class LoggingMiddleware(BaseMiddleware):
    def __init__(self, name: str) -> None:
        self.name = name

    async def wrap_model(self, call_next, **request):
        logger.info("{}: before model", self.name)

        try:
            async with aclosing(call_next(**request)) as stream:
                async for event in stream:
                    yield event

        except Exception:
            logger.exception(
                "{}: model stream raised an exception",
                self.name,
            )
            raise

        finally:
            logger.info("{}: model stream exited", self.name)


def build_model_handler(terminal, middlewares):
    """将中间件依次包在底层模型调用外面。"""

    handler = terminal

    for middleware in reversed(middlewares):
        handler = partial(
            middleware.wrap_model,
            handler,
        )

    return handler
