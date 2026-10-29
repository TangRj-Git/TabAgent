from contextlib import AsyncExitStack

from tabagent.mcp_new.mcp_client import MCPServerClient


class MCPClientManager:
    def __init__(
            self,
            clients: dict[str, MCPServerClient],
    ) -> None:
        # 保存所有客户端对象。
        self.clients = clients

        # 保存连接的清理操作，在主动关闭时执行。
        self._stack: AsyncExitStack | None = None

    async def connect(self) -> None:
        """连接所有客户端；返回后连接继续保持。"""
        if self._stack is not None:
            return

        stack = AsyncExitStack()

        try:
            for server_client in self.clients.values():
                client = server_client.client

                # 最终关闭时，释放底层传输资源。
                stack.push_async_callback(client.close)

                # 建立连接，并登记退出时的清理操作。
                await stack.enter_async_context(client)

        except BaseException:
            # 启动失败或被取消时，清理已打开的连接。
            await stack.aclose()
            raise

        # 保存 stack，不在 connect() 返回时关闭它。
        self._stack = stack

    async def aclose(self) -> None:
        """关闭所有客户端连接。"""
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
