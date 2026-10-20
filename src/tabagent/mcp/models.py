"""可复制的目录快照；不包含连接、锁、配置凭据或可执行对象。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from mcp_types import (
    Implementation,
    Prompt,
    Resource,
    ResourceTemplate,
    ServerCapabilities,
    Tool,
)

DiscoveryStatus = Literal[
    "unloaded",
    "ready",
    "unsupported",
    "failed",
]
ConnectionStatus = Literal[
    "disabled",
    "disconnected",
    "connecting",
    "connected",
    "closing",
    "failed",
]


@dataclass
class MCPErrorInfo:
    server_id: str
    operation: str
    message: str
    exception_type: str
    category: str = "unknown"
    cause_type: str | None = None
    status_code: int | None = None
    error_code: int | None = None


@dataclass
class MCPCollection[T]:
    status: DiscoveryStatus = "unloaded"
    items: list[T] = field(default_factory=list)
    error: MCPErrorInfo | None = None
    stale: bool = False
    updated_at: datetime | None = None


@dataclass
class MCPServerInfo:
    server_id: str
    transport: Literal["stdio", "http", "sse"]
    state: ConnectionStatus = "disconnected"
    server_info: Implementation | None = None
    protocol_version: str | None = None
    capabilities: ServerCapabilities | None = None
    instructions: str | None = None
    error: MCPErrorInfo | None = None
    cleanup_error: MCPErrorInfo | None = None
    cleanup_pending: bool = False


@dataclass
class MCPServerCatalog:
    server_id: str
    tools: MCPCollection[Tool] = field(default_factory=MCPCollection)
    resources: MCPCollection[Resource] = field(default_factory=MCPCollection)
    prompts: MCPCollection[Prompt] = field(default_factory=MCPCollection)
    resource_templates: MCPCollection[ResourceTemplate] = field(default_factory=MCPCollection)


@dataclass
class MCPCatalog:
    servers: dict[str, MCPServerCatalog] = field(default_factory=dict)


@dataclass
class MCPToolDefinition:
    """聚合查询结果；保留来源和原始工具定义，不改名、不转换 Schema。"""

    server_id: str
    tool: Tool
