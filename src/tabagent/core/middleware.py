from functools import partial
from typing import Sequence

from tabagent.middleware.base_middleware import (
    BaseMiddleware,
    AppInitHandler,
    AgentHandler,
    ModelHandler,
    ToolHandler,
)


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
        """组装初始化中间件调用链，返回调用入口。"""

        # terminal 是最终的初始化方法，例如 self._initialize。
        # 这里只保存方法本身，没有调用它，因此不会创建 LLM 和 Agent。
        handler = terminal

        # 从最后一个中间件开始包装，
        # 使列表中的第一个中间件最终位于最外层。
        for middleware in reversed(self._middlewares):
            # partial 会创建一个新的可调用对象，
            # 将当前 handler 提前绑定为 wrap_init 的 call_next 参数。
            # request 参数暂时不传，留到真正执行时再提供。
            #
            # 此时不会执行：
            # 1. middleware.wrap_init 的函数体。
            # 2. 下一层 handler 的函数体。
            # 3. 最底层 terminal 的函数体。
            #
            # 因此，这一步只连接调用关系，不会修改请求参数。
            # 右侧 handler 是之前的入口，赋值后左侧 handler 是新入口。
            handler = partial(
                middleware.wrap_init,
                handler,
            )

        # 返回组装好的入口，此时整条初始化调用链尚未执行。
        # 后续通过 await handler(request) 才会开始执行。
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
