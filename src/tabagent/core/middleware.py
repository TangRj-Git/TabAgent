from functools import partial
from typing import Sequence

from tabagent.middleware.base_middleware import BaseMiddleware, AppInitHandler, AgentHandler, ModelHandler, ToolHandler


class MiddlewareManager:
    """按注册顺序组装中间件，第一个中间件位于最外层。"""

    def __init__(
            self,
            middlewares: Sequence[BaseMiddleware] = (),
    ) -> None:
        self._middlewares = middlewares

    def build_init(
            self,
            terminal: AppInitHandler,
    ) -> AppInitHandler:
        handler = terminal

        for middleware in reversed(self._middlewares):
            handler = partial(middleware.wrap_init, handler)

        return handler

    def build_agent(
            self,
            terminal: AgentHandler,
    ) -> AgentHandler:
        handler = terminal

        for middleware in reversed(self._middlewares):
            handler = partial(middleware.wrap_agent, handler)

        return handler

    def build_model(
            self,
            terminal: ModelHandler,
    ) -> ModelHandler:
        handler = terminal

        for middleware in reversed(self._middlewares):
            handler = partial(middleware.wrap_model, handler)

        return handler

    def build_tool(
            self,
            terminal: ToolHandler,
    ) -> ToolHandler:
        handler = terminal

        for middleware in reversed(self._middlewares):
            handler = partial(middleware.wrap_tool, handler)

        return handler
