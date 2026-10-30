from types import TracebackType
from typing import Literal, Any

from fastmcp import Client
from fastmcp.client.transports import ClientTransport
from mcp_types import Tool, CallToolResult

from tabagent.core.function import Function
from tabagent.mcp_new.mcp_model import MCPServerInfo, MCPServerCatalog

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


class MCPServerClient:
    """
    封装单个 MCP 服务的客户端。

    创建实例时只构造客户端对象，不会建立连接。
    使用 async with 或 AsyncExitStack 进入异步上下文后，
    才会建立连接并完成 MCP 协议初始化，同时返回当前 MCPServerClient 对象。

    get_server_info()、get_catalog() 以及底层客户端的工具调用，
    都需要在连接保持打开期间使用，这些方法不会自动建立连接。

    退出异步上下文时，调用底层客户端的退出方法，执行连接清理。
    """

    def __init__(
            self,
            server_id: str,
            transport: ClientTransport,
            transport_type: Literal["stdio", "sse", "http", "streamable-http"],
    ) -> None:
        """FastMCP 的连接和请求操作是异步的。"""
        self.server_id = server_id
        self.transport = transport
        self.transport_type = transport_type

        self.client = Client(
            name=self.server_id,
            transport=self.transport,
        )

    def get_server_info(self) -> MCPServerInfo:
        """读取当前连接中的服务端基础信息。"""
        if not self.client.is_connected():
            raise RuntimeError("MCP client is not connected.")

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
        return await self.client.call_tool(
            name=name,
            arguments=arguments,
        )

    async def __aenter__(self) -> "MCPServerClient":
        """建立底层连接，并返回当前包装对象。"""
        await self.client.__aenter__()
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
    ) -> None:
        """退出客户端上下文，释放连接。"""
        await self.client.__aexit__(exc_type, exc_value, traceback)
