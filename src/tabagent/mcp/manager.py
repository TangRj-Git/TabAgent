import asyncio
from typing import Any

from fastmcp.client.client import CallToolResult
from mcp_types import Tool

from tabagent.core.function import Function
from tabagent.mcp.create_transport import create_transport
from tabagent.mcp.client import MCPClientStatus, MCPServerClient
from tabagent.mcp.model import MCPAllServersInfo, MCPAllServersCatalog
from tabagent.mcp.transport import MCPClientConfig


class MCPServerClientManager:
    """
    保存多个 MCP 客户端，每个客户端独立管理自己的连接。

    创建实例时只构造客户端，调用 connect() 后建立连接。
    连接保持期间，可以按 server_id 获取客户端并调用工具。
    普通服务启动失败时记录错误，必需服务失败时在批量启动结束后抛出异常。
    所有业务调用结束后，使用 aclose() 最终关闭，之后禁止再次启动服务。

    一个实例只在同一个事件循环中使用。
    """

    def __init__(
            self,
            mcp_client_config: MCPClientConfig,
            *,
            connect_timeout: float = 180.0,
            required_servers: set[str] | None = None,
    ) -> None:
        self._required_servers = frozenset(required_servers or ())
        unknown = self._required_servers - mcp_client_config.servers.keys()
        if unknown:
            raise ValueError(f"Unknown required MCP servers: {sorted(unknown)}.")

        self._clients: dict[str, MCPServerClient] = {
            server_id: MCPServerClient(
                server_id=server_id,
                transport=create_transport(config),
                transport_type=config.transport,
                connect_timeout=connect_timeout,
            )
            for server_id, config in mcp_client_config.servers.items()
        }
        self._closed = False

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("MCP client manager is closed.")

    def _lookup(self, server_id: str) -> MCPServerClient:
        """查找客户端，不要求它已经连接。"""
        try:
            return self._clients[server_id]
        except KeyError:
            raise KeyError(f"Unknown MCP server: {server_id!r}.") from None

    def _connected_clients(self) -> dict[str, MCPServerClient]:
        """返回当前可用客户端的快照，供目录汇总使用。"""
        self._require_open()
        return {
            server_id: client
            for server_id, client in self._clients.items()
            if client.is_connected()
        }

    async def connect(self) -> dict[str, str | None]:
        """依次启动；结果中 None 表示成功，字符串表示错误，取消请求继续传播。"""
        self._require_open()
        results: dict[str, str | None] = {}

        for server_id in self._clients:
            self._require_open()
            try:
                await self.connect_server(server_id)
            except Exception as error:
                results[server_id] = f"{type(error).__name__}: {error}"
            else:
                results[server_id] = None

        self._require_open()
        failures = {
            server_id: results[server_id]
            for server_id in self._required_servers
            if results[server_id] is not None
        }
        if failures:
            # 已成功连接的服务仍保留，由调用方决定继续使用或统一关闭。
            raise RuntimeError(f"Required MCP servers failed: {failures}")
        return results

    async def connect_server(self, server_id: str) -> None:
        """连接指定服务。"""
        self._require_open()
        await self._lookup(server_id).connect()

    async def disconnect_server(self, server_id: str) -> None:
        """断开指定服务，之后允许重新连接。"""
        self._require_open()
        await self._lookup(server_id).disconnect()

    async def reconnect_server(self, server_id: str) -> None:
        """重新连接指定服务。"""
        self._require_open()
        await self._lookup(server_id).reconnect()

    def get_status(self, server_id: str) -> MCPClientStatus:
        """查询指定服务的状态，管理器关闭后也允许查询。"""
        return self._lookup(server_id).get_status()

    def get_all_statuses(self) -> dict[str, MCPClientStatus]:
        """查询所有服务的状态。"""
        return {
            server_id: client.get_status()
            for server_id, client in self._clients.items()
        }

    def get_all_server_infos(self) -> MCPAllServersInfo:
        """读取所有已连接服务的基础信息，按 server_id 保存。"""
        result: MCPAllServersInfo = MCPAllServersInfo()

        for server_id, server_client in self._connected_clients().items():
            result.servers[server_id] = server_client.get_server_info()

        return result

    async def get_all_catalogs(self) -> MCPAllServersCatalog:
        """依次获取所有已连接服务的能力目录，按 server_id 保存。"""
        result: MCPAllServersCatalog = MCPAllServersCatalog()

        for server_id, server_client in self._connected_clients().items():
            result.servers[server_id] = await server_client.get_catalog()

        return result

    async def get_all_tools(self) -> list[Tool]:
        """依次获取所有已连接服务的原始工具目录，并合并返回。"""
        tools: list[Tool] = []

        for server_client in self._connected_clients().values():
            tools.extend(await server_client.get_tools())

        return tools

    async def get_all_functions(self) -> list[Function]:
        """依次获取所有已连接服务的函数定义，并合并返回。"""
        functions: list[Function] = []

        for server_client in self._connected_clients().values():
            functions.extend(await server_client.get_functions())

        return functions

    def get_client(
            self,
            server_id: str,
    ) -> MCPServerClient:
        """根据服务标识获取已连接的客户端。"""
        self._require_open()
        server_client = self._lookup(server_id)

        if not server_client.is_connected():
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
        """最终关闭全部客户端；尝试全部清理后，汇总抛出关闭异常。"""
        self._closed = True
        clients = list(self._clients.values())
        results = await asyncio.gather(
            *(client.aclose() for client in clients),
            return_exceptions=True,
        )
        errors: list[BaseException] = []
        for client, result in zip(clients, results):
            if isinstance(result, BaseException):
                result.add_note(f"MCP server: {client.server_id}")
                errors.append(result)
        if errors:
            raise BaseExceptionGroup("Failed to close MCP clients.", errors)
