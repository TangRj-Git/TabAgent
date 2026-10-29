from tabagent.middleware.base_middleware import BaseMiddleware, AppInitHandler, AppInitRequest


class MCPMiddleware(BaseMiddleware):
    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        pass
