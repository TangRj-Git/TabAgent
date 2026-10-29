from dataclasses import dataclass, field
from typing import Literal

from mcp_types import (
    Tool,
    Resource,
    Prompt,
    ResourceTemplate,
    Implementation,
    ServerCapabilities,
)


@dataclass
class MCPServerInfo:
    """保存一个 MCP 服务端的基础信息。"""

    server_id: str
    transport: Literal["stdio", "sse", "http", "streamable-http"]
    instructions: str | None = None
    protocol_version: str | None = None
    server_info: Implementation | None = None
    server_capabilities: ServerCapabilities | None = None


@dataclass
class MCPServerCatalog:
    """保存一个 MCP 服务的能力目录。"""

    tools: list[Tool] = field(default_factory=list)
    prompts: list[Prompt] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    resource_templates: list[ResourceTemplate] = field(default_factory=list)


@dataclass
class MCPAllServersCatalog:
    """保存所有 MCP 服务的能力目录；字典的键为 server_id，值为对应服务的目录。"""

    servers: dict[str, MCPServerCatalog] = field(default_factory=dict)
