import asyncio
from contextlib import AsyncExitStack
from typing import Any

from mcp_types import CallToolResult, Tool

from tabagent.core.function import Function
from tabagent.mcp_new.create_transport import create_transport
from tabagent.mcp_new.mcp_client import MCPServerClient
from tabagent.mcp_new.mcp_model import MCPAllServersInfo, MCPAllServersCatalog
from tabagent.mcp_new.mcp_transport import MCPClientConfig


class MCPServerClientManager:
    """
    管理多个 MCP 客户端。

    创建实例时只构造客户端，调用 connect() 后建立连接。
    连接保持期间，可以按 server_id 获取客户端并调用工具。
    所有业务调用结束后，使用 aclose() 统一关闭。

    一个实例只在同一个事件循环中使用。
    """

    def __init__(
            self,
            mcp_client_config: MCPClientConfig,
    ) -> None:
        self._clients: dict[str, MCPServerClient] = {
            server_id: MCPServerClient(
                server_id=server_id,
                transport=create_transport(serverConfig),
                transport_type=serverConfig.transport,
            )
            for server_id, serverConfig in mcp_client_config.servers.items()
        }

        # 持有各客户端的异步上下文，直到统一关闭。
        self._stack: AsyncExitStack | None = None

        # 防止多次连接或关闭操作同时进行。
        self._lifecycle_lock = asyncio.Lock()

    async def connect(self) -> None:
        """依次连接所有服务；任一连接失败时，清理本次已打开的连接。"""
        async with self._lifecycle_lock:
            if self._stack is not None:
                return

            stack = AsyncExitStack()

            try:
                for server_client in self._clients.values():
                    # 提前登记关闭操作，连接失败时也能清理。
                    # 显式 close() 还会关闭 keep_alive=True 的传输。
                    stack.push_async_callback(server_client.client.close)

                    # 进入包装对象的上下文，建立底层连接。
                    await stack.enter_async_context(server_client)

            except BaseException:
                # 包括连接异常，以及连接过程中收到的取消请求。
                await stack.aclose()
                raise

            self._stack = stack

    def get_all_server_infos(self) -> MCPAllServersInfo:
        """读取所有已连接服务的基础信息，按 server_id 保存。"""
        if self._stack is None:
            raise RuntimeError("MCP client manager is not connected.")

        result: MCPAllServersInfo = MCPAllServersInfo()

        for server_id, server_client in self._clients.items():
            result.servers[server_id] = server_client.get_server_info()

        return result

    async def get_all_catalogs(self) -> MCPAllServersCatalog:
        """依次获取所有已连接服务的能力目录，按 server_id 保存。"""
        if self._stack is None:
            raise RuntimeError("MCP client manager is not connected.")

        result: MCPAllServersCatalog = MCPAllServersCatalog()

        for server_id, server_client in self._clients.items():
            result.servers[server_id] = await server_client.get_catalog()

        return result

    async def get_all_tools(self) -> list[Tool]:
        """依次获取所有已连接服务的原始工具目录，并合并返回。"""
        if self._stack is None:
            raise RuntimeError("MCP client manager is not connected.")

        tools: list[Tool] = []

        for server_client in self._clients.values():
            tools.extend(await server_client.get_tools())

        return tools

    async def get_all_functions(self) -> list[Function]:
        """依次获取所有已连接服务的函数定义，并合并返回。"""
        if self._stack is None:
            raise RuntimeError("MCP client manager is not connected.")

        functions: list[Function] = []

        for server_client in self._clients.values():
            functions.extend(await server_client.get_functions())

        return functions

    def get_client(
            self,
            server_id: str,
    ) -> MCPServerClient:
        """根据服务标识获取已连接的客户端。"""
        if self._stack is None:
            raise RuntimeError("MCP client manager is not connected.")

        try:
            server_client = self._clients[server_id]
        except KeyError:
            raise KeyError(f"Unknown MCP server: {server_id!r}.") from None

        if not server_client.client.is_connected():
            raise RuntimeError(
                f"MCP server {server_id!r} is not connected."
            )

        return server_client

    async def call_tool(
            self,
            server_id: str,
            name: str,
            arguments: dict[str, Any] | None = None,
    ) -> CallToolResult:
        """通过指定服务的客户端调用工具。"""
        server_client = self.get_client(server_id)

        return await server_client.call_tool(
            name=name,
            arguments=arguments,
        )

    async def aclose(self) -> None:
        """统一退出客户端上下文并关闭底层连接。"""
        async with self._lifecycle_lock:
            if self._stack is None:
                return

            stack = self._stack
            self._stack = None

            await stack.aclose()
