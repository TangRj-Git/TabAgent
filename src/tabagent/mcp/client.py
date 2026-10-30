import asyncio
import math
from contextlib import AsyncExitStack
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Any

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import ClientTransport
from mcp_types import Tool

from tabagent.core.function import Function
from tabagent.mcp.model import MCPServerInfo, MCPServerCatalog

TOOL_TEMPLATE = {
    "name": "get_current_time",
    "title": "null",
    "description": "Get current time in a specific timezone",
    "input_schema": {
        "type": "object",
        "properties": {
            "timezone": {
                "description": "IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Use 'Asia/Shanghai' as local timezone if no timezone provided by the user.",
                "title": "Timezone",
                "type": "string"
            }
        },
        "required": [
            "timezone"
        ],
        "title": "get_current_timeArguments"
    },
    "execution": "null",
    "output_schema": {
        "properties": {
            "timezone": {
                "title": "Timezone",
                "type": "string"
            },
            "datetime": {
                "title": "Datetime",
                "type": "string"
            },
            "day_of_week": {
                "title": "Day Of Week",
                "type": "string"
            },
            "is_dst": {
                "title": "Is Dst",
                "type": "boolean"
            }
        },
        "required": [
            "timezone",
            "datetime",
            "day_of_week",
            "is_dst"
        ],
        "title": "TimeResult",
        "type": "object"
    },
    "icons": "null",
    "annotations": {
        "title": "null",
        "read_only_hint": "true",
        "destructive_hint": "false",
        "idempotent_hint": "true",
        "open_world_hint": "false"
    },
    "meta": "null"
}


ClientState = Literal[
    "disconnected", "connecting", "connected", "closing", "failed", "closed",
]


@dataclass(frozen=True)
class MCPClientStatus:
    """一个客户端当前的状态快照。"""

    server_id: str
    state: ClientState
    error: str | None = None


class MCPServerClient:
    """
    封装单个 MCP 服务的客户端。

    创建实例时不会建立连接；connect() 建立连接，disconnect() 断开连接，
    reconnect() 重连。aclose() 最终关闭对象，之后禁止重新连接。

    也支持单独通过 async with 或 AsyncExitStack 使用，退出上下文时断开连接。
    由管理器持有时，业务代码直接调用方法，不再嵌套进入同一对象的上下文。

    查询目录和调用工具都要求已经连接，不会自动建立连接。
    生命周期锁不等待正在进行的工具调用，最终关闭前应先结束业务调用。
    一个实例只在同一个事件循环中使用。
    """

    def __init__(
            self,
            server_id: str,
            transport: ClientTransport,
            transport_type: Literal["stdio", "sse", "http", "streamable-http"],
            *,
            connect_timeout: float = 180.0,
    ) -> None:
        """FastMCP 的连接和请求操作是异步的。"""
        if not math.isfinite(connect_timeout) or connect_timeout <= 0:
            raise ValueError("connect_timeout must be finite and positive.")

        self.server_id = server_id
        self.transport = transport
        self.transport_type = transport_type

        self.client = Client(
            name=self.server_id,
            transport=self.transport,
            init_timeout=connect_timeout,
        )

        self._connect_timeout = connect_timeout
        self._stack: AsyncExitStack | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._state: ClientState = "disconnected"
        self._last_error: str | None = None
        self._closed = False

    def is_connected(self) -> bool:
        """判断当前是否允许使用连接。"""
        return (
            not self._closed
            and self._state == "connected"
            and self.client.is_connected()
        )

    def get_status(self) -> MCPClientStatus:
        """返回状态快照，并结合底层客户端检查连接状态。"""
        state = self._state
        if self._closed and state not in ("closed", "failed"):
            state = "closing"
        elif state == "connected" and not self.client.is_connected():
            state = "disconnected"
        return MCPClientStatus(self.server_id, state, self._last_error)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"MCP client {self.server_id!r} is closed.")

    def _require_connected(self) -> None:
        if not self.is_connected():
            raise RuntimeError(f"MCP server {self.server_id!r} is not connected.")

    async def connect(self) -> None:
        """建立连接；已连接时直接返回。"""
        async with self._lifecycle_lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        """只能在已经持有生命周期锁时调用。"""
        self._require_open()
        if self.is_connected():
            return

        # 重连之前清理旧上下文或上一次失败残留的资源。
        if self._stack is not None or self._state == "failed":
            await self._disconnect_locked()
            self._require_open()

        self._state = "connecting"
        self._last_error = None
        stack = AsyncExitStack()
        # 登记方法本身；退出上下文后再显式关闭 keep_alive=True 的传输。
        stack.push_async_callback(self.client.close)
        self._stack = stack

        try:
            async with asyncio.timeout(self._connect_timeout):
                await stack.enter_async_context(self.client)
        except BaseException as error:
            # 连接失败或被取消时，只清理当前服务。
            try:
                await self._disconnect_locked()
            except BaseException as cleanup_error:
                self._state = "failed"
                self._last_error = (
                    f"{type(error).__name__}: {error}; "
                    f"cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}"
                )
                if not isinstance(cleanup_error, Exception):
                    raise
                raise error from cleanup_error
            self._state = "failed"
            self._last_error = f"{type(error).__name__}: {error}"
            raise

        self._state = "connected"

    async def disconnect(self) -> None:
        """断开连接，之后仍然允许 connect()。"""
        async with self._lifecycle_lock:
            if self._state != "closed":
                await self._disconnect_locked()

    async def _disconnect_locked(self) -> None:
        """只能在已经持有生命周期锁时调用。"""
        self._state = "closing"
        stack, self._stack = self._stack, None
        try:
            if stack is not None:
                await stack.aclose()
            else:
                # 清理失败后退出栈可能已耗尽，仍需重试底层关闭。
                await self.client.close()
        except BaseException as error:
            self._state = "failed"
            self._last_error = f"{type(error).__name__}: {error}"
            raise

        self._state = "closed" if self._closed else "disconnected"
        self._last_error = None

    async def reconnect(self) -> None:
        """在同一把锁内完成断开和重新连接。"""
        async with self._lifecycle_lock:
            self._require_open()
            await self._disconnect_locked()
            await self._connect_locked()

    async def aclose(self) -> None:
        """最终关闭；禁止重新连接，清理失败时允许再次调用以重试。"""
        self._closed = True
        async with self._lifecycle_lock:
            if self._state != "closed":
                await self._disconnect_locked()

    def get_server_info(self) -> MCPServerInfo:
        """读取当前连接中的服务端基础信息。"""
        self._require_connected()

        return MCPServerInfo(
            server_id=self.server_id,
            transport=self.transport_type,
            instructions=self.client.instructions,
            protocol_version=self.client.protocol_version,
            server_info=self.client.server_info,
            server_capabilities=self.client.server_capabilities,
        )

    async def get_catalog(self) -> MCPServerCatalog:
        """按服务端声明的能力获取目录。"""
        self._require_connected()
        capabilities = self.client.server_capabilities
        if capabilities is None:
            raise RuntimeError("MCP client must be connected and initialized.")

        catalog = MCPServerCatalog()

        if capabilities.tools is not None:
            catalog.tools = await self.client.list_tools()
        if capabilities.prompts is not None:
            catalog.prompts = await self.client.list_prompts()
        if capabilities.resources is not None:
            catalog.resources = await self.client.list_resources()
            catalog.resource_templates = await self.client.list_resource_templates()

        return catalog

    async def get_tools(self) -> list[Tool]:
        """获取工具目录；客户端需已连接，不支持工具时返回空列表。"""
        self._require_connected()
        capabilities = self.client.server_capabilities
        if capabilities is None:
            raise RuntimeError("MCP client must be connected and initialized.")

        if capabilities.tools is None:
            return []

        return await self.client.list_tools()

    async def get_functions(self) -> list[Function]:
        """将当前服务的工具目录转换为提供给模型的函数定义。"""
        tools = await self.get_tools()

        functions: list[Function] = []

        for tool in tools:
            functions.append(
                Function(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.input_schema,
                    output_schema=tool.output_schema,
                    strict=False,
                )
            )

        return functions

    async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any] | None = None,
    ) -> CallToolResult:
        """按名称和参数调用当前服务的工具，返回执行结果；客户端需已连接。"""
        self._require_connected()
        return await self.client.call_tool(
            name=name,
            arguments=arguments,
        )

    async def __aenter__(self) -> "MCPServerClient":
        """建立底层连接，并返回当前包装对象。"""
        await self.connect()
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
    ) -> None:
        """退出客户端上下文，释放连接。"""
        await self.disconnect()
